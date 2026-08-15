# Mobile Imaging Unit Scheduling API — Product Requirements Document

## 1. Introduction

Operating a fleet of mobile MRI, CT, and PET coaches is a logistics problem wrapped in a compliance problem wrapped in a billing problem. Each week, every trailer-mounted scanner must be routed across contracted hospital and clinic pads; each on-site day must be staffed with a certified technologist whose travel and radiation-dose limits are respected; each pad must be verified for power, levelness, cooling, shielding, and network uplink before the first patient is scanned; and when something breaks — a chiller failure at 06:40, an expired accreditation, a facility that cancels with four hours of notice — the day must be unwound, rescheduled, and billed in a way that both the operator and the facility can audit line by line.

This document specifies the Mobile Imaging Unit Scheduling API, the system of record for that operation. It governs the full chain from network setup (facilities, units, contracts) through week planning (route plans, site day assignments, transport legs), day execution (setup checklists, staffing, patient appointments, scanning), disruption handling (cancellation, breakdown, interruption, rescheduling with credit carry-over), compliance (accreditation records, radiation dose records), image transfer to the reading radiologist, and finally billing (per-day and per-scan statements, disputes, and monthly contract settlement with volume discounts). All rules herein are deterministic: given the same logical clock and the same request history, any conforming implementation must produce byte-identical amounts, statuses, and error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` to identify the acting user and `X-User-Role` to declare the capacity in which they act. The system recognizes exactly five roles, spelled precisely as follows: `OperationsDirector`, `FacilityCoordinator`, `Technologist`, `ReadingRadiologist`, and `ComplianceOfficer`. A request missing either header, or declaring a role outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is declared but not permitted for the targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `FacilityCoordinator`, `X-User-ID` is the `id` of the acting `ContractedFacility`; ownership checks on any resource that references a facility — booking an appointment against one of that facility's site days, or disputing a billing statement — compare the resource's facility foreign key to `X-User-ID`. When `X-User-Role` is `Technologist`, `X-User-ID` is the `id` of the acting `Technologist`; ownership checks compare the relevant technologist foreign key to `X-User-ID`, most strictly on dose-record creation where the payload's technologist must be the caller. When `X-User-Role` is `OperationsDirector`, `ReadingRadiologist`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Many list endpoints additionally accept resource-specific filter query parameters (for example, the unit list accepts `modality` and `active_breakdown_id`, and the contract list accepts `facility_id`); each filter narrows the listing to exact matches on the named field, and the relevant filters are introduced alongside each resource in §3.

### 2.4. The Logical Clock, Dates, and Times

The server never reads the wall clock. Instead it maintains a logical clock whose value at startup is exactly `2026-08-01T00:00:00Z`. Every server-stamped timestamp in the system — creation and modification stamps, scan completion stamps, image delivery and acknowledgement stamps — reads this logical clock. An `OperationsDirector` may advance the logical clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. Advancing the clock is not a passive read: it re-derives every accreditation record's time-based status and fires the expiry cascade described in §3.7.

Two field formats recur throughout the API. Calendar dates such as `service_date`, `week_start_date`, `issued_on`, and `expires_on` are `YYYY-MM-DD` strings. Time-of-day fields such as `arrival_time`, `first_patient_time`, `last_patient_time`, `departure_time`, and `scheduled_start` are `HH:MM` strings in 24-hour UTC, interpreted on the owning entity's service date.

### 2.5. Common Resource Properties

All primary resources — facilities, units, contracts, route plans, site day assignments, appointments, technologists, staffing assignments, transport legs, setup checklists, breakdown events, accreditation records, billing statements, and image studies — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every mutation.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including mutations caused by cascades and recomputed derived fields. Newly created resources begin at `version` 1.

The single exception is the `RadiationDoseRecord`, which is immutable once written: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

### 2.6. Monetary Precision and Rounding Conventions

All money in the system is integer cents. Contract rates, statement amounts, stipends, credits, and invoice totals are stored and returned as whole-cent integers. Whenever a multiplication or proration produces a fractional cent — a late-cancellation percentage, an interruption proration, a mileage stipend, a volume discount — the result is rounded half-up to whole cents at the step the relevant rule prescribes. Rounding order matters and is pinned per calculation: travel stipends are rounded per leg before summing, never summed and then rounded.

Radiation dose quantities are decimal numbers of millisieverts carried to 2 decimal places with round-half-up rounding; diagnostic-reference-level comparisons are made at 1 decimal place. Durations, drive times, and window lengths are whole minutes. Transport distances (`distance_miles`) preserve input precision of up to 2 decimal places.

### 2.7. Optimistic Concurrency Control

Two write endpoints require the caller to prove it has observed the current state of a parent entity, protecting week planning from silent overwrites. Both checks are evaluated immediately after existence checks and before any state or business rule, so a stale version surfaces as a version error rather than being masked by a later validation.

Creating a route plan requires the request body to carry `expected_unit_version`, the `version` of the target `MobileImagingUnit` as the client last observed it. If the unit's current `version` has advanced since that observation — for example because another plan creation for the same unit and week has already legitimately superseded the prior draft — the create is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412).

Rescheduling an interrupted site day requires the request body to carry `expected_route_plan_version`, the `version` of the target `RoutePlan` as the client last observed it. If the target plan's `version` has advanced in the meantime — its day roster may have changed — the reschedule is rejected with `ERR_STALE_ROUTE_PLAN_VERSION` (HTTP 412). Endpoints not named in this subsection take no version field at all.

### 2.8. Validation Order and Identifier Resolution

Every request is validated against a fixed priority ladder, and a failure at any rung stops evaluation so that earlier errors mask later ones. The order is:

1. Authentication context: `X-User-ID` and `X-User-Role` are present and the role is declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Authorization: the role is permitted for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence: every path identifier and every body foreign key — `route_plan_id`, `facility_id`, `contract_id`, `site_day_id`, `technologist_id`, `appointment_id`, `unit_id`, `target_route_plan_id` — resolves to an existing resource. Path identifiers on nested URLs are validated left to right, and the first identifier that does not resolve produces that resource's 404 before later segments are even examined. The existence family comprises `ERR_FACILITY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROUTE_PLAN_NOT_FOUND`, `ERR_SITE_DAY_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_TECHNOLOGIST_NOT_FOUND`, `ERR_STAFFING_NOT_FOUND`, `ERR_TRANSPORT_LEG_NOT_FOUND`, `ERR_CHECKLIST_NOT_FOUND`, `ERR_BREAKDOWN_NOT_FOUND`, `ERR_ACCREDITATION_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, and the generic `ERR_NOT_FOUND`.
4. Optimistic concurrency: `expected_unit_version` and `expected_route_plan_version` mismatches (`ERR_STALE_UNIT_VERSION`, `ERR_STALE_ROUTE_PLAN_VERSION`), deliberately checked before state and business rules.
5. State preconditions: the target entity must be in the transition's required from-state (`ERR_INVALID_STATE` and its more specific siblings such as `ERR_PLAN_NOT_PUBLISHED`, `ERR_SITE_DAY_NOT_BOOKABLE`, `ERR_STATEMENT_NOT_FINALIZABLE`).
6. Radiation and staffing safety: the projected-dose gate and the CT/PET-only dose-record rule.
7. Pad power: nameplate supply at site-day creation and measured amperage at mark-ready.
8. Identity and ownership linkage: the acting coordinator's facility matches the resource's facility; a dose record's technologist is the caller; the acting technologist is staffed on the day.
9. Credential linkage: technologist certifications, exam-type modality prefixes, facility modality support, and contract-facility agreement.
10. Temporal placement: service dates not in the past, service dates inside the plan week, and well-formed on-site windows.
11. Resource conflicts: unit day-exclusivity, appointment slot placement and overlap, single-day staffing, drive-time ceilings, and the one-checklist-per-day rule.
12. Accreditation: the unit's governing record is valid at the gated operations.
13. Fiscal gates: the contract's monthly scan cap.
14. Payment exactness: a payment must match the statement's net due to the cent.

Independently of this ladder, any request with a missing required field, a type mismatch, or an enum value outside the declared set is rejected with `ERR_INVALID_REQUEST`.

### 2.9. Day-Level Cascades and Capacity Invariants

A site day assignment is the operational hub of the system, and its state transitions are never shallow. When a day completes, is cancelled, or is interrupted, the server reconciles everything hanging off that day in the same transaction: its appointments are moved to their appropriate terminal states, its staffing assignments are released with the matching reason, its transport legs are failed or cancelled, and exactly one billing statement is created for the day. Cascaded mutations obey the common-property rules of §2.5: every mutated resource refreshes `updated_at` and increments `version`.

Four capacity invariants hold across the fleet. A unit works at most one live day per calendar date (§3.2). A technologist holds at most one `ASSIGNED` staffing assignment per calendar date (§3.3). A site day has exactly one setup checklist (§3.4) and exactly one billing statement over its lifetime (§3.9). These invariants are discrete and count-based: they bind even when the colliding records would never overlap in continuous time.

### 2.10. Radiation Safety and Accreditation Posture

Two compliance postures cut across every operational workflow and are summarized here so the gates read consistently wherever they appear. First, radiation exposure is managed prospectively and retrospectively: before a technologist may be staffed on a day, the system projects their dose for that date against a hard daily ceiling of 5.0 mSv (§3.3); after scans complete, delivered doses are recorded, compared against per-exam diagnostic reference levels, and aggregated into daily and monthly totals (§3.7). Second, no unit may be booked, dispatched, or readied unless its governing accreditation record is currently valid; when a governing record lapses past its expiry date, the clock itself cancels the unit's future scheduled days at no charge to the facility (§3.7).

## 3. Business Logic & Workflows

### 3.1. Standing Up the Network: Facilities, Units, and Service Contracts

Everything begins with the contracted network. An `OperationsDirector` registers a `ContractedFacility` with a `name`, the street `address` of the pad site, the `supported_modalities` the facility hosts (any of `MRI`, `CT`, `PET`), and the electrical pad specification: `pad_amps_available` of shore-power amperage, the `pad_voltage` supply, and `pad_level_tolerance_deg`, the maximum pad slope in degrees the facility certifies. Facilities may be listed by every role, and individual facilities fetched the same way.

A `MobileImagingUnit` is registered with a unique operator `unit_code`, its `modality` (one of `MRI`, `CT`, or `PET`), the `power_required_amps` the scanner draws, the `voltage_required` it must be fed, the `setup_minutes` needed from arrival to first-patient readiness, the `teardown_minutes` needed from last patient to roadworthy departure, and the `home_base_name` depot where the unit stages. A new unit enters in `ACTIVE_SERVICE` status with `version` 1 and a null `active_breakdown_id`; the unit list can be narrowed with the optional `modality` and `active_breakdown_id` filters. The pad and the unit must electrically agree before a day may be placed: at site-day creation the facility's `pad_amps_available` must be at least the unit's `power_required_amps` and the facility's `pad_voltage` must equal the unit's `voltage_required`, failing which the placement is rejected with `ERR_PAD_POWER_INSUFFICIENT`. A facility must also host the unit's modality — a `PET` coach cannot be routed to a pad whose `supported_modalities` omits `PET` — or the placement fails with `ERR_MODALITY_NOT_SUPPORTED`.

The commercial terms live on the `ServiceContract`. Creating one requires the `facility_id` it serves, the `billing_model` (`PER_DAY` or `PER_SCAN`), and a block of rate fields whose meaning depends on that model. `day_rate_cents` is the full on-site day price under `PER_DAY`. Under `PER_SCAN`, `scan_rate_cents` is the per-scan price within quota, `included_scan_quota` is the number of scans per day billed at that rate before the overage rate applies, `overage_scan_rate_cents` prices each scan beyond the quota, `guaranteed_minimum_cents` floors the charge when a held day completes zero scans, and `no_show_fee_cents` is charged per `NO_SHOW` appointment. Cancellation terms are shared: `cancel_notice_hours` draws the line between an early and a late cancel, and `cancel_late_pct` is the fraction of the day rate (under `PER_DAY`) or of the guaranteed minimum (under `PER_SCAN`) charged on a late cancel. `monthly_scan_cap` caps bookable non-cancelled appointments per calendar month under the contract, and `interruption_floor_cents` is the minimum charge when a `PER_DAY` day is interrupted. Contracts can be listed (optionally filtered by `facility_id`) and fetched by all roles; §3.9 explains how these fields price a day, and why the contract's model is snapshotted onto every statement.

### 3.2. Planning the Week: Route Plans, Site Days, and Transport Legs

An `OperationsDirector` plans one week at a time. Creating a `RoutePlan` takes the `unit_id` being routed and a `week_start_date`, which is always a Monday; the plan covers the seven-day window from `week_start_date` through six days later, inclusive. The create must also carry `expected_unit_version` per §2.7. The new plan starts `DRAFT`. If a plan already exists for the same unit and week start and it is still `DRAFT`, that earlier plan is automatically moved to `SUPERSEDED` and the new plan's `supersedes_plan_id` points at it; if the earlier plan is `PUBLISHED` or `LOCKED`, the create instead fails with `ERR_PLAN_WEEK_CONFLICT`. Every successful plan creation also increments the unit's `version` by one, which is precisely what makes a second writer's cached unit version stale. Plans can be listed with optional `unit_id`, `status`, and `supersedes_plan_id` filters.

A plan is fleshed out with `SiteDayAssignment` records, each created with the `route_plan_id` containing the day, the host `facility_id`, the billing `contract_id`, the `service_date`, and four times: `arrival_time`, `first_patient_time`, `last_patient_time`, and `departure_time`. The day may be added while the plan is `DRAFT` or `PUBLISHED`; against a plan in any other state the attempt is rejected with `ERR_PLAN_NOT_PUBLISHED`, and locking a plan (below) is exactly how new site days — and inbound reschedules — are blocked. Creation enforces a battery of placement rules. The service date must not precede the logical clock date (`ERR_SERVICE_DATE_IN_PAST`) and must fall inside the plan's seven-day week (`ERR_SERVICE_DATE_OUTSIDE_PLAN_WEEK`). The window must be geometrically well-formed: `first_patient_time` no earlier than `arrival_time` plus the unit's `setup_minutes`, and `departure_time` no earlier than `last_patient_time` plus the unit's `teardown_minutes` — otherwise `ERR_WINDOW_TOO_SHORT`. The contract must belong to the day's facility, meaning the contract's `facility_id` equals the day's `facility_id`, or `ERR_CONTRACT_FACILITY_MISMATCH`. The pad-power, voltage, and modality-support rules of §3.1 apply here, as does the accreditation gate of §3.7. Finally, unit day-exclusivity is enforced: if any other site day exists for the same unit on the same `service_date` in a status other than `CANCELLED` or `RESCHEDULED`, creation is rejected with `ERR_UNIT_DAY_DOUBLE_BOOKED` — capacity is a whole calendar day, so two same-date days with disjoint time windows still conflict. A created day starts `SCHEDULED`, its `unit_id` is denormalized from the plan at creation, and the plan's `version` increments by one while its `site_day_count` — the count of the plan's site days in any status — increases by one. Site days can be listed with filters on `route_plan_id`, `unit_id`, `facility_id`, `contract_id`, `status`, `service_date`, `rescheduled_from_id`, and `rescheduled_to_id`.

The publication cycle is deliberate. Publishing requires the plan to be `DRAFT` and to contain at least one site day: a publish against a non-draft plan fails with `ERR_PLAN_NOT_PUBLISHED`, and an empty plan fails with `ERR_EMPTY_ROUTE_PLAN`. Unpublishing returns a `PUBLISHED` plan to `DRAFT`, but only when every one of its days is still `SCHEDULED` or already `CANCELLED`; a plan with any day past scheduling is rejected with `ERR_PLAN_HAS_ACTIVE_DAYS`, and a plan that is not `PUBLISHED` is rejected with `ERR_PLAN_NOT_PUBLISHED`. The `DRAFT` → `PUBLISHED` → `DRAFT` cycle may repeat freely. Locking moves `PUBLISHED` → `LOCKED` (again `ERR_PLAN_NOT_PUBLISHED` guards the from-state). Closing moves `LOCKED` → `CLOSED`; it requires the plan to be `LOCKED` (`ERR_PLAN_NOT_LOCKED`) and every day terminal — `COMPLETED`, `CANCELLED`, or `RESCHEDULED` — else `ERR_PLAN_HAS_ACTIVE_DAYS`. `CLOSED` and `SUPERSEDED` are terminal plan states.

Each day is reached by road, so an `OperationsDirector` also plans `TransportLeg` records against a site day: the day's `site_day_id`, an `origin_name` (a depot or a prior site), a `destination_name`, the road `distance_miles`, the estimated `drive_minutes`, and an optional `overnight` flag marking legs the crew sleeps over before driving. A new leg starts `PLANNED` and immediately earns its stipend: `stipend_cents` is the leg's `distance_miles` multiplied by the fleet mileage rate of 67 cents per mile, rounded half-up to whole cents, plus a flat per diem of 15,000 cents when `overnight` is true. The plan's `total_travel_stipend_cents` is then recomputed as the sum of the per-leg stipends across all of the plan's site days — each leg rounded first, then summed, in that pinned order — and legs keep their stipend even if they later end `FAILED` or `CANCELLED`, because the cost was committed at dispatch planning. When departure is called on the day (§3.4), each of its `PLANNED` legs is dispatched automatically (`PLANNED` → `DISPATCHED`); a `Technologist` or `OperationsDirector` then marks each dispatched leg arrived, moving `DISPATCHED` → `ARRIVED` (a leg in any other state answers `ERR_INVALID_STATE`). Legs can be listed with `site_day_id` and `status` filters.

### 3.3. Staffing the Day: Certifications, Drive Time, and Dose Projection

Technologists are the scarce resource. An `OperationsDirector` registers each `Technologist` with a `full_name`, their `modality_certs` (a subset of `MRI`, `CT`, `PET`), their `home_base_name` for travel estimation, and `max_daily_drive_minutes`, the longest one-way drive they accept in a day. Two computed exposure fields ride on the record: `current_day_dose_msv`, the sum of that technologist's recorded doses on appointments whose site day's `service_date` equals the logical clock date, and `monthly_dose_msv`, the same sum over the logical clock's calendar month. Both start at zero and are recomputed as dose records arrive (§3.7).

Staffing a day means creating a `StaffingAssignment` with the `site_day_id`, the `technologist_id`, and an `estimated_drive_minutes` one-way home-to-site estimate. Four gates guard the create, and they compose with the §2.8 ladder. The technologist's `modality_certs` must contain the day's unit modality, else `ERR_MODALITY_CERT_MISMATCH`. The `estimated_drive_minutes` must not exceed the technologist's `max_daily_drive_minutes`, else `ERR_DRIVE_TIME_EXCEEDED`. The technologist must hold no other `ASSIGNED` staffing on the same `service_date`, else `ERR_STAFFING_DATE_CONFLICT`. And the prospective dose gate runs: `projected_dose_msv` is computed as the sum of the technologist's dose records dated on the target day's `service_date` plus the sum of `estimated_dose_msv` over the target day's appointments still in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or `SCANNING`; if that projection is strictly greater than the 5.0 mSv daily technologist limit, the assignment is rejected with `ERR_DOSE_LIMIT_EXCEEDED` — a projection landing exactly on the limit is allowed. A created assignment starts `ASSIGNED` with the computed `projected_dose_msv` stored on it, and assignments may be listed with `site_day_id`, `technologist_id`, and `status` filters.

An assignment leaves `ASSIGNED` in two ways. An `OperationsDirector` may release it manually — an optional `reason` may accompany the call — which lands it in `RELEASED` with `release_reason` `MANUAL`. Or the day itself ends: completion, cancellation, and interruption each release all of the day's `ASSIGNED` staffing with `release_reason` `DAY_COMPLETED`, `DAY_CANCELLED`, or `DAY_INTERRUPTED` respectively. `RELEASED` is terminal; releasing anything not `ASSIGNED` answers `ERR_INVALID_STATE`.

### 3.4. The On-Site Day: Departure, Setup, and the Checklist

A `SCHEDULED` day starts moving when an `OperationsDirector` calls departure. The day must be `SCHEDULED` (`ERR_INVALID_STATE`) and the unit's governing accreditation must be `ACTIVE` or `EXPIRING_SOON` (`ERR_ACCREDITATION_NOT_VALID`); the day then advances `SCHEDULED` → `EN_ROUTE`, and every `PLANNED` transport leg of the day cascades to `DISPATCHED`.

Once on site, setup begins. Advancing `EN_ROUTE` → `SETTING_UP` requires every transport leg of the day to be `ARRIVED` — a straggler leg surfaces as `ERR_TRANSPORT_NOT_ARRIVED` — with the usual `ERR_INVALID_STATE` guarding the from-state. During `SETTING_UP` a `Technologist` records the day's `SetupChecklist`, one per site day: a second checklist for the same day is rejected with `ERR_CHECKLIST_EXISTS`, and recording against a day that is not in `SETTING_UP` is an `ERR_INVALID_STATE`. The checklist captures five boolean verifications and two measurements: `power_verify_passed` with the hookup's `measured_amps`, `pad_level_passed`, `chiller_passed`, `rf_shield_passed`, and `network_link_passed` with the `measured_uplink_mbps`. Its `status` is computed, never set: `IN_PROGRESS` before any record exists, `ALL_PASSED` when all five booleans are true, and `HAS_FAILURES` as soon as any one is false. Failed items are not fatal — a `Technologist` re-records a single item by naming its `item_key`, the new `passed` value, and, where applicable, a `measured_value` that overwrites `measured_amps` for the `POWER_VERIFY` item or `measured_uplink_mbps` for the `NETWORK_LINK` item; the checklist status is then recomputed, so the `HAS_FAILURES` → `ALL_PASSED` cycle repeats until everything passes. Checklists may be listed with a `site_day_id` filter.

Marking the day ready — `SETTING_UP` → `READY` — is the strictest gate on the pad. It requires the day to be `SETTING_UP` (`ERR_INVALID_STATE`), the day's checklist to exist with status `ALL_PASSED` (`ERR_CHECKLIST_INCOMPLETE`), the recorded `measured_amps` to be at least the unit's `power_required_amps` (`ERR_PAD_POWER_INSUFFICIENT`), and the governing accreditation to be `ACTIVE` or `EXPIRING_SOON` (`ERR_ACCREDITATION_NOT_VALID`).

Starting service — `READY` → `IN_SERVICE` — additionally requires at least one `ASSIGNED` staffing assignment on the day, failing which the call is rejected with `ERR_NO_STAFF_ASSIGNED`.

Completing the day — `IN_SERVICE` → `COMPLETED` — requires every appointment of the day to be terminal: `COMPLETED`, `CANCELLED`, or `NO_SHOW`; any open appointment blocks the close with `ERR_OPEN_APPOINTMENTS`. On completion the day's `delivered_service_minutes` is set to the full planned window, that is the minutes from `first_patient_time` to `last_patient_time`; all remaining `ASSIGNED` staffing is released as `DAY_COMPLETED`; and the system auto-creates the day's billing statement in `PROVISIONAL` status using the provisional pricing variant of §3.9.

### 3.5. Patient Appointments: Booking Rules and the Scanning Flow

A `FacilityCoordinator` books a `PatientAppointment` into one of their own facility's site days — if the acting coordinator's facility differs from the day's facility, the booking is rejected with `ERR_FACILITY_MISMATCH`. The payload names the `site_day_id`, an opaque `patient_ref` from the facility EMR, the `exam_type` (`CT_HEAD`, `CT_CHEST`, `MRI_BRAIN`, or `PET_ONCO`), the `scheduled_start` time, the `duration_minutes` of scanner occupancy (a positive number), an optional `sedation_required` flag defaulting to false, the projected `estimated_dose_msv`, and an optional `insurance_preauth` reference.

Booking is gated by slot feasibility, credential agreement, and the contract's fiscal cap. The day must be bookable — a day that is `INTERRUPTED`, `CANCELLED`, `COMPLETED`, or `RESCHEDULED` accepts no appointments and answers `ERR_SITE_DAY_NOT_BOOKABLE`. The exam's modality prefix must match the day's unit modality: `CT_HEAD` and `CT_CHEST` against a `CT` unit, `MRI_BRAIN` against an `MRI` unit, `PET_ONCO` against a `PET` unit; a mismatch is `ERR_MODALITY_NOT_SUPPORTED`. The slot must sit inside the service window: `scheduled_start` no earlier than `first_patient_time`, and the appointment's effective end — `scheduled_start` plus `duration_minutes` plus a 15-minute sedation buffer when `sedation_required` is true — no later than `last_patient_time`, with the window close inclusive so an effective end exactly equal to `last_patient_time` is allowed; violations are `ERR_SLOT_OUTSIDE_WINDOW`. The slot must also not collide with the day's existing appointments in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or `SCANNING` (appointments already `COMPLETED`, `CANCELLED`, or `NO_SHOW` do not block). Collision uses half-open intervals with a 10-minute trailing turnover buffer on each appointment's effective end: a new appointment conflicts with an existing one when the new start is earlier than the existing appointment's effective end plus ten minutes and the existing appointment's start is earlier than the new appointment's effective end plus ten minutes. Any conflict is rejected with `ERR_SLOT_OVERLAP`. Last of all — it is the fiscal gate on the §2.8 ladder, so all earlier checks fire first — the contract's `monthly_scan_cap` is enforced: counting every appointment on site days under the same contract whose `service_date` falls in the target calendar month and whose status is anything but `CANCELLED`, the booking is rejected with `ERR_SCAN_CAP_EXCEEDED` when that count has already reached the cap; booking the appointment that reaches the cap is allowed, and only the next one is refused. A booked appointment starts `REQUESTED`. Appointments may be listed with `site_day_id` and `status` filters.

The appointment lifecycle mirrors the patient journey. An `OperationsDirector` confirms a `REQUESTED` appointment (`CONFIRMED`); a `FacilityCoordinator` checks the patient in once the day is `READY` or `IN_SERVICE` (`CHECKED_IN`, with `ERR_SITE_DAY_NOT_IN_SERVICE` if the day has not reached at least `READY`); a `Technologist` begins the scan from `CHECKED_IN` (`SCANNING`) but only while the day is `IN_SERVICE` (`ERR_SITE_DAY_NOT_IN_SERVICE`) and only when the acting technologist — the caller's `X-User-ID` — holds an `ASSIGNED` staffing assignment on that site day (`ERR_TECHNOLOGIST_NOT_STAFFED`). The same staffed-technologist rule guards scan completion, which moves `SCANNING` → `COMPLETED` and stamps `completed_at` from the logical clock. Every out-of-order transition answers `ERR_INVALID_STATE`.

Two off-ramps exist. A `FacilityCoordinator` may cancel an appointment while it is `REQUESTED` or `CONFIRMED`, optionally supplying a `reason`; a manual cancel sets the appointment's `cancel_reason` to `PATIENT_CANCELLED`, and cancelling from any other state is rejected with `ERR_APPOINTMENT_NOT_CANCELLABLE`. (Day-level cascades reach further — they may also cancel `CHECKED_IN` and even `SCANNING` appointments, per §3.6.) And while the day is `IN_SERVICE`, a coordinator may mark a `CONFIRMED` appointment `NO_SHOW` (`ERR_SITE_DAY_NOT_IN_SERVICE` if the day is not in service, `ERR_INVALID_STATE` if the appointment is not `CONFIRMED`). `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal. The appointment's `actual_dose_msv` starts at zero and becomes the sum of its dose records once technologists post them (§3.7).

### 3.6. When the Day Goes Wrong: Cancellation, Interruption, Breakdown, and Rescheduling

Plans collide with reality in four ways, and each has a precise unwind.

**Cancellation.** While a day is `SCHEDULED` or `EN_ROUTE`, an `OperationsDirector` or a `FacilityCoordinator` may cancel it, supplying `notice_hours` — how many hours before service the cancellation arrives. From any other state the cancel is `ERR_INVALID_STATE`. Cancellation stamps the day's `cancel_reason` as `FACILITY_CANCEL` and unwinds the day: appointments in `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` are cancelled with `cancel_reason` `DAY_CANCELLED`; `ASSIGNED` staffing is released as `DAY_CANCELLED`; transport legs still `PLANNED` become `CANCELLED` while legs already `DISPATCHED` become `FAILED`; and the day's billing statement is auto-created in `PROVISIONAL` with the cancellation fee priced per the contract — the charge is late, and priced as such, exactly when `notice_hours` is less than the contract's `cancel_notice_hours`. The day also supports a system-driven cancellation: when the unit's governing accreditation expires, future `SCHEDULED` days are cancelled with `cancel_reason` `ACCREDITATION_EXPIRED` and a zero-fee statement (§3.7). (`cancel_reason` may also hold `PROVIDER_CANCEL` in the data model.)

**Interruption.** A day that is `SETTING_UP`, `READY`, or `IN_SERVICE` may be interrupted, either by an `OperationsDirector` calling the interruption action with a `reason`, or automatically as the second hop of a breakdown cascade. The supplied reason is recorded as the day's `interrupt_reason`, one of `BREAKDOWN` or `OPERATOR_INTERRUPT`. Interruption freezes delivered service at the minutes elapsed from `first_patient_time` to the logical clock, clamped below at zero and above at the full planned window length, and stores it in `delivered_service_minutes`. The unwind then mirrors cancellation with interruption semantics: appointments in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or `SCANNING` are cancelled with `cancel_reason` `DAY_INTERRUPTED`; `ASSIGNED` staffing is released as `DAY_INTERRUPTED`; `DISPATCHED` legs become `FAILED`; and a `PROVISIONAL` billing statement is auto-created using the provisional pricing variant — under `PER_DAY` that means the prorated charge with its interruption floor and its compensating credit (§3.9).

**Breakdowns.** A `Technologist` or `OperationsDirector` reports a `BreakdownEvent` with the failed `unit_id`, an optional `site_day_id` naming the day in progress (null when the unit fails off-duty), a `severity`, and a free-text `description`; the event starts `REPORTED`. Severity drives the cascade. A `MINOR` breakdown cascades to nothing — the day continues. A `MAJOR` breakdown interrupts the named day exactly as the interruption action does. A `CRITICAL` breakdown does that and additionally takes the unit off the road: the unit transitions `ACTIVE_SERVICE` → `OUT_OF_SERVICE` with its `active_breakdown_id` set to the new event's `id` — a unit already `OUT_OF_SERVICE` rejects the report with `ERR_UNIT_OUT_OF_SERVICE`. An `OperationsDirector` later resolves a `REPORTED` event by recording `downtime_hours` and `resolution_notes`; resolving anything not `REPORTED` is `ERR_BREAKDOWN_ALREADY_RESOLVED`. When the resolved event is `CRITICAL` and is the unit's `active_breakdown_id`, resolution returns the unit to `ACTIVE_SERVICE` and clears `active_breakdown_id` to null. Breakdowns may be listed with `unit_id` and `site_day_id` filters.

**Planned downtime.** Between breakdowns, an `OperationsDirector` may send an `ACTIVE_SERVICE` unit to `MAINTENANCE` — provided the unit has no site day in `EN_ROUTE`, `SETTING_UP`, `READY`, or `IN_SERVICE`, else `ERR_UNIT_HAS_ACTIVE_DAY` — and later return it `MAINTENANCE` → `ACTIVE_SERVICE`. Both actions guard their from-state with `ERR_INVALID_STATE`.

**Rescheduling.** An interrupted day can be rebuilt inside another week plan. The reschedule action names a `target_route_plan_id`, carries `expected_route_plan_version` per §2.7 (the stale-version check fires before any business rule), and supplies a complete replacement geometry: `new_service_date`, `new_arrival_time`, `new_first_patient_time`, `new_last_patient_time`, and `new_departure_time`. The source day must be `INTERRUPTED` (`ERR_RESCHEDULE_SOURCE_INVALID`). The target plan must exist, be `PUBLISHED`, and belong to the same unit (`ERR_RESCHEDULE_TARGET_INVALID`). The new date must not be before the logical clock date, must fall inside the target plan's week, must satisfy the same window-geometry rules as a fresh site day, and must pass unit day-exclusivity (`ERR_UNIT_DAY_DOUBLE_BOOKED`). On success a replacement day is created `SCHEDULED` in the target plan with the same `facility_id` and `contract_id`, its `rescheduled_from_id` pointing back to the source; the source day becomes `RESCHEDULED` with its `rescheduled_to_id` pointing at the replacement; the target plan's `version` increments by one; and the billing linkage is recorded so that the replacement day's eventual statement carries `credit_applied_cents` equal to the source statement's `credit_granted_cents` (§3.9).

### 3.7. Compliance Oversight: Accreditation and Radiation Dose Records

A `ComplianceOfficer` maintains each unit's `AccreditationRecord`s, created with the `unit_id`, the `accrediting_body` (`ACR`, `IAC`, or `TJC`), the `modality` the record governs (`MRI`, `CT`, or `PET` — the governing record for a unit is chosen among records matching the unit's modality), the `issued_on` date, and the `expires_on` date. Status is clock-derived rather than stored opinion: a record is `EXPIRED` when `expires_on` is before the logical clock date, `EXPIRING_SOON` when the clock date is between zero and thirty days before expiry inclusive, and `ACTIVE` when expiry is more than thirty days out; a new record's initial status is derived from the clock at creation by the same rule. A record may also be manually suspended — an audit finding — moving `ACTIVE` or `EXPIRING_SOON` to `SUSPENDED` with the supplied `reason` stored as `suspend_reason` (`ERR_INVALID_STATE` from any other state), and later reinstated, at which point the landing state is re-derived from the clock: `ACTIVE` if expiry is more than thirty days out, `EXPIRING_SOON` within the thirty-day window, `EXPIRED` if the date has passed. Suspend and reinstate may cycle freely. Every advance of the logical clock re-derives these statuses across all records. Records may be listed with `unit_id` and `status` filters.

The **governing record** for a unit is the modality-matching record with the latest `expires_on`; ties break toward the record created later. Site-day creation, departure, and mark-ready each require the governing record to be `ACTIVE` or `EXPIRING_SOON` — a governing record that is `EXPIRED` or `SUSPENDED`, or a unit with no governing record at all, fails the gate with `ERR_ACCREDITATION_NOT_VALID`. When a governing record flips to `EXPIRED` under a clock advance, the cascade is automatic and punitive to the operator, not the facility: every `SCHEDULED` site day for that unit whose `service_date` is after the clock date is cancelled with `cancel_reason` `ACCREDITATION_EXPIRED`, its `REQUESTED` and `CONFIRMED` appointments are cancelled with `cancel_reason` `DAY_CANCELLED`, and a zero-amount `PROVISIONAL` statement is created for each such day.

Radiation dose is recorded per scan. After an appointment completes, a `Technologist` posts a `RadiationDoseRecord` carrying the `appointment_id`, the `technologist_id`, and the delivered `dose_msv`. Three identity and applicability rules bind: the appointment must be `COMPLETED` (`ERR_INVALID_STATE` otherwise); the payload's `technologist_id` must equal the caller's `X-User-ID` (`ERR_TECHNOLOGIST_IDENTITY_MISMATCH`); and the acting technologist must hold an `ASSIGNED` staffing assignment on that day (`ERR_TECHNOLOGIST_NOT_STAFFED`). Dose records exist only for ionizing modalities — `CT_HEAD`, `CT_CHEST`, and `PET_ONCO`; an MRI exam emits no ionizing dose and posting one is rejected with `ERR_DOSE_NOT_APPLICABLE`. Each record is checked against the diagnostic reference level for its exam type, and `drl_exceeded` is set true exactly when `dose_msv` is strictly greater than the reference level — 2.0 mSv for `CT_HEAD`, 7.0 mSv for `CT_CHEST`, 10.0 mSv for `PET_ONCO`; equality does not flag, the record is accepted regardless, and the flag is advisory for compliance audit. Posting a record recomputes the recording technologist's `current_day_dose_msv` and `monthly_dose_msv` and the appointment's `actual_dose_msv`. Per §2.5 a dose record is immutable: it has no `updated_at` and no `version`. Records may be listed with `appointment_id` and `technologist_id` filters.

### 3.8. Image Transfer and the Reading Workflow

A completed scan produces images that must reach the reading radiologist. A `Technologist` registers an `ImageStudy` against a `COMPLETED` appointment (`ERR_INVALID_STATE` otherwise) with the `appointment_id`, the DICOM `study_uid`, and the payload `size_mb`; the study starts `QUEUED` with `transfer_attempts` zero and both `delivered_at` and `acknowledged_at` null.

Transmission is deterministic, driven entirely by the day's measured uplink. When a `Technologist` transmits a `QUEUED` study (any other state answers `ERR_STUDY_NOT_TRANSFERRABLE`), the system computes the transfer budget as sixty seconds of transfer at the measured uplink: the floor of the site day checklist's `measured_uplink_mbps` multiplied by 7.5, in megabytes. A study whose `size_mb` is within the budget — the boundary is inclusive — passes through `TRANSMITTING` inside the call and lands `DELIVERED`, with `delivered_at` stamped from the logical clock; a study over budget lands `TRANSFER_FAILED`. Either way `transfer_attempts` increments by one. A failed study is not dead: a `Technologist` may retry it, returning `TRANSFER_FAILED` → `QUEUED` (again `ERR_STUDY_NOT_TRANSFERRABLE` guards the from-state) for another transmit once conditions improve. Studies may be listed with `appointment_id` and `status` filters.

The loop closes when a `ReadingRadiologist` acknowledges a `DELIVERED` study (`ERR_INVALID_STATE` from any other state), optionally attaching `reader_notes`. Acknowledgement stamps `acknowledged_at` from the logical clock and computes the turnaround flag: `sla_breached` is true exactly when the elapsed time from the appointment's `completed_at` to `acknowledged_at` is strictly greater than 120 minutes. `ACKNOWLEDGED` is terminal. Delivery status feeds billing: under `PER_SCAN`, only completed appointments whose study has reached `DELIVERED` or `ACKNOWLEDGED` are billable at finalize time (§3.9).

### 3.9. Billing: Statements, Disputes, and Contract Settlement

A `BillingStatement` is never created by hand. Exactly one statement per site day is auto-created the moment the day completes, is cancelled, or is interrupted, carrying the day's `site_day_id`, the `contract_id` copied from the day, and `billing_model_snapshot` pinned from the contract at creation so later contract edits never reprice history. The statement starts `PROVISIONAL` and accumulates computed counters: `completed_scan_count` of the day's `COMPLETED` appointments and `no_show_count` of its `NO_SHOW` appointments.

The day's charge has two variants along one axis and two models along the other. The provisional variant, computed at day close, counts every `COMPLETED` appointment as billable. The final variant, computed at finalization, tightens `PER_SCAN` to count only `COMPLETED` appointments whose image study is `DELIVERED` or `ACKNOWLEDGED` at that moment — scans without delivered images drop out of the billable set. Within either variant, the model selected by `billing_model_snapshot` prices the day. Under `PER_DAY`: a completed day bills exactly `day_rate_cents`; an interrupted day bills the day rate multiplied by the fraction of the planned window actually delivered — `delivered_service_minutes` over the minutes from `first_patient_time` to `last_patient_time` — rounded half-up to whole cents, but never less than `interruption_floor_cents`, and the difference between the day rate and that prorated amount is recorded as the statement's `credit_granted_cents`; a cancelled day bills nothing when the cancel was early or provider-caused (`ACCREDITATION_EXPIRED`), and otherwise bills `day_rate_cents` multiplied by `cancel_late_pct`, rounded half-up to whole cents. Under `PER_SCAN`: the charge is the billable count up to `included_scan_quota` times `scan_rate_cents`, plus any billable count beyond the quota times `overage_scan_rate_cents`, plus `no_show_count` times `no_show_fee_cents`; and when the day reached `READY` at least once yet the billable count is zero, the charge is raised to at least `guaranteed_minimum_cents`. A late `PER_SCAN` cancellation bills `guaranteed_minimum_cents` multiplied by `cancel_late_pct`, rounded half-up; early or provider-caused cancels bill nothing. The computed amount lands in `provisional_amount_cents` at creation and, after finalization, in `final_amount_cents` (null until then). While `PROVISIONAL`, `net_due_cents` equals `provisional_amount_cents` minus `credit_applied_cents`; once finalized, it equals `final_amount_cents` minus `credit_applied_cents`.

The credit fields link an interrupted day to its replacement across the reschedule chain. On the interrupted source day's `PER_DAY` statement, `credit_granted_cents` is the day rate minus the statement's provisional amount; the replacement day's statement then carries `credit_applied_cents` equal to that granted credit. The money invariant follows: when the replacement day completes a full window, the two statements' `net_due_cents` sum to exactly the contract's `day_rate_cents`. Under `PER_SCAN` the invariant is a count: the billable scans across both statements equal the number of distinct `COMPLETED` appointments across both days, because appointments cancelled by the interruption (`DAY_INTERRUPTED`) are never billable, so a rebooked scan is billed exactly once. Both statements, and indeed all statements, may be listed with `site_day_id`, `contract_id`, and `status` filters.

Settlement walks the statement through its lifecycle. An `OperationsDirector` finalizes a `PROVISIONAL` statement (`ERR_STATEMENT_NOT_FINALIZABLE` from any other state), which recomputes the final variant — including the delivered-image billable set for `PER_SCAN` — and restates `net_due_cents` against the final amount. A `FacilityCoordinator` of the statement's own facility may dispute a `FINALIZED` statement with a `reason` (a coordinator from another facility is refused with `ERR_FACILITY_MISMATCH`, and a non-finalized statement with `ERR_INVALID_STATE`), moving it to `DISPUTED`. An `OperationsDirector` resolves the dispute with a `resolution`: `UPHOLD` returns the statement to `FINALIZED` with amounts unchanged, while `ADJUST` overwrites `final_amount_cents` with the supplied `adjusted_amount_cents` and recomputes `net_due_cents`; the `FINALIZED` → `DISPUTED` → `FINALIZED` cycle may repeat. From `FINALIZED`, invoicing moves the statement to `INVOICED`, and marking it paid requires the tendered `paid_amount_cents` to equal `net_due_cents` exactly — anything else is `ERR_PAYMENT_AMOUNT_MISMATCH` — before the statement lands in its terminal `PAID` state.

One computed read rolls the month up for the whole contract. Given a `month` (`YYYY-MM`), the period invoice sums `net_due_cents` over the contract's statements in `FINALIZED`, `INVOICED`, or `PAID` whose site day's `service_date` falls inside that month, inclusive of both ends, yielding `gross_cents`. The volume tier is then selected on the gross — never on the discounted figure, which would be circular: a gross of at least 1,000,000 cents earns 8 percent, a gross of at least 500,000 cents earns 5 percent, and anything below earns nothing. The `discount_cents` is the gross multiplied by the selected `tier_pct` and divided by one hundred, rounded half-up to whole cents, and `net_cents` is the gross minus the discount. The response returns `month`, `gross_cents`, `tier_pct`, `discount_cents`, and `net_cents`, in that pinned evaluation order.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including every state-transition action, return `200 OK`. The logical-clock endpoint returns `200 OK`. All resources are mounted under the `/api` prefix. Request payloads, validation rules, and side effects for each operation are specified by the workflows in §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; re-derives accreditation statuses and fires the expiry cascade | OperationsDirector |
| POST | `/api/facilities` | Create a contracted facility | OperationsDirector |
| GET | `/api/facilities` | List facilities | All roles |
| GET | `/api/facilities/{id}` | Get a facility | All roles |
| POST | `/api/units` | Create a mobile imaging unit (`ACTIVE_SERVICE`, version 1) | OperationsDirector |
| GET | `/api/units` | List units (filters `modality`, `active_breakdown_id`) | All roles |
| GET | `/api/units/{id}` | Get a unit | All roles |
| POST | `/api/units/{id}/maintenance` | Send a unit to `MAINTENANCE` (no in-flight site day) | OperationsDirector |
| POST | `/api/units/{id}/return-to-service` | Return a unit from `MAINTENANCE` to `ACTIVE_SERVICE` | OperationsDirector |
| POST | `/api/contracts` | Create a service contract for a facility | OperationsDirector |
| GET | `/api/contracts` | List contracts (filter `facility_id`) | All roles |
| GET | `/api/contracts/{id}` | Get a contract | All roles |
| GET | `/api/contracts/{id}/period-invoice` | Monthly rollup with gross-selected volume discount tier | OperationsDirector |
| POST | `/api/route-plans` | Create a week route plan (`DRAFT`); supersedes same-unit-week `DRAFT`; OCC on unit version | OperationsDirector |
| GET | `/api/route-plans` | List route plans (filters `unit_id`, `status`, `supersedes_plan_id`) | All roles |
| GET | `/api/route-plans/{id}` | Get a route plan | All roles |
| POST | `/api/route-plans/{id}/publish` | Publish a `DRAFT` plan (requires at least one site day) | OperationsDirector |
| POST | `/api/route-plans/{id}/unpublish` | Return a `PUBLISHED` plan to `DRAFT` (days must be `SCHEDULED`/`CANCELLED`) | OperationsDirector |
| POST | `/api/route-plans/{id}/lock` | Lock a `PUBLISHED` plan (blocks new site days and reschedule-in) | OperationsDirector |
| POST | `/api/route-plans/{id}/close` | Close a `LOCKED` plan (all days terminal) | OperationsDirector |
| POST | `/api/site-days` | Assign a unit to a facility for one service date inside a plan week | OperationsDirector |
| GET | `/api/site-days` | List site days (filters `route_plan_id`, `unit_id`, `facility_id`, `contract_id`, `status`, `service_date`, `rescheduled_from_id`, `rescheduled_to_id`) | All roles |
| GET | `/api/site-days/{id}` | Get a site day | All roles |
| POST | `/api/site-days/{id}/depart` | `SCHEDULED` → `EN_ROUTE`; dispatches `PLANNED` transport legs | OperationsDirector |
| POST | `/api/site-days/{id}/begin-setup` | `EN_ROUTE` → `SETTING_UP`; requires all legs `ARRIVED` | OperationsDirector |
| POST | `/api/site-days/{id}/mark-ready` | `SETTING_UP` → `READY`; checklist `ALL_PASSED`, power, accreditation | OperationsDirector |
| POST | `/api/site-days/{id}/start-service` | `READY` → `IN_SERVICE`; requires at least one `ASSIGNED` technologist | OperationsDirector |
| POST | `/api/site-days/{id}/complete` | `IN_SERVICE` → `COMPLETED`; auto-creates `PROVISIONAL` statement | OperationsDirector |
| POST | `/api/site-days/{id}/cancel` | `SCHEDULED`/`EN_ROUTE` → `CANCELLED`; cascades; fee per contract notice | OperationsDirector, FacilityCoordinator |
| POST | `/api/site-days/{id}/interrupt` | `SETTING_UP`/`READY`/`IN_SERVICE` → `INTERRUPTED` (operator-initiated) | OperationsDirector |
| POST | `/api/site-days/{id}/reschedule` | `INTERRUPTED` → `RESCHEDULED`; creates replacement day in a target `PUBLISHED` plan; OCC on target plan version | OperationsDirector |
| POST | `/api/appointments` | Book a patient into a site day's on-site window | FacilityCoordinator |
| GET | `/api/appointments` | List appointments (filters `site_day_id`, `status`) | All roles |
| GET | `/api/appointments/{id}` | Get an appointment | All roles |
| POST | `/api/appointments/{id}/confirm` | `REQUESTED` → `CONFIRMED` | OperationsDirector |
| POST | `/api/appointments/{id}/check-in` | `CONFIRMED` → `CHECKED_IN` (day `READY` or `IN_SERVICE`) | FacilityCoordinator |
| POST | `/api/appointments/{id}/begin-scan` | `CHECKED_IN` → `SCANNING` (day `IN_SERVICE`; acting technologist staffed) | Technologist |
| POST | `/api/appointments/{id}/complete-scan` | `SCANNING` → `COMPLETED`; stamps `completed_at` | Technologist |
| POST | `/api/appointments/{id}/cancel` | `REQUESTED`/`CONFIRMED` → `CANCELLED` (`PATIENT_CANCELLED`) | FacilityCoordinator |
| POST | `/api/appointments/{id}/mark-no-show` | `CONFIRMED` → `NO_SHOW` (day `IN_SERVICE`) | FacilityCoordinator |
| POST | `/api/technologists` | Create a technologist | OperationsDirector |
| GET | `/api/technologists` | List technologists | All roles |
| GET | `/api/technologists/{id}` | Get a technologist (including computed dose fields) | All roles |
| POST | `/api/staffing-assignments` | Assign a technologist to a site day; computes `projected_dose_msv` and enforces cert, dose, drive-time, and date-conflict gates | OperationsDirector |
| GET | `/api/staffing-assignments` | List staffing assignments (filters `site_day_id`, `technologist_id`, `status`) | All roles |
| GET | `/api/staffing-assignments/{id}` | Get a staffing assignment | All roles |
| POST | `/api/staffing-assignments/{id}/release` | `ASSIGNED` → `RELEASED` (`MANUAL`) | OperationsDirector |
| POST | `/api/transport-legs` | Plan a transport leg; computes per-leg stipend and recomputes plan total | OperationsDirector |
| GET | `/api/transport-legs` | List transport legs (filters `site_day_id`, `status`) | All roles |
| GET | `/api/transport-legs/{id}` | Get a transport leg | All roles |
| POST | `/api/transport-legs/{id}/arrive` | `DISPATCHED` → `ARRIVED` | Technologist, OperationsDirector |
| POST | `/api/setup-checklists` | Record the full setup checklist for a day in `SETTING_UP` (one per day) | Technologist |
| GET | `/api/setup-checklists` | List checklists (filter `site_day_id`) | All roles |
| GET | `/api/setup-checklists/{id}` | Get a checklist | All roles |
| POST | `/api/setup-checklists/{id}/record-item` | Overwrite one checklist item; recomputes status | Technologist |
| POST | `/api/breakdowns` | Report a breakdown; `MINOR` no cascade, `MAJOR` interrupts the day, `CRITICAL` also takes the unit `OUT_OF_SERVICE` | Technologist, OperationsDirector |
| GET | `/api/breakdowns` | List breakdowns (filters `unit_id`, `site_day_id`) | All roles |
| GET | `/api/breakdowns/{id}` | Get a breakdown | All roles |
| POST | `/api/breakdowns/{id}/resolve` | `REPORTED` → `RESOLVED`; a `CRITICAL` resolution returns the unit to `ACTIVE_SERVICE` | OperationsDirector |
| POST | `/api/dose-records` | Record delivered dose for a `COMPLETED` CT/PET appointment; sets `drl_exceeded`; recomputes aggregates | Technologist |
| GET | `/api/dose-records` | List dose records (filters `appointment_id`, `technologist_id`) | All roles |
| GET | `/api/dose-records/{id}` | Get a dose record | All roles |
| POST | `/api/accreditations` | Create an accreditation record (initial status derived from the clock) | ComplianceOfficer |
| GET | `/api/accreditations` | List accreditation records (filters `unit_id`, `status`) | All roles |
| GET | `/api/accreditations/{id}` | Get an accreditation record | All roles |
| POST | `/api/accreditations/{id}/suspend` | `ACTIVE`/`EXPIRING_SOON` → `SUSPENDED` (audit finding) | ComplianceOfficer |
| POST | `/api/accreditations/{id}/reinstate` | `SUSPENDED` → clock-derived `ACTIVE` / `EXPIRING_SOON` / `EXPIRED` | ComplianceOfficer |
| GET | `/api/billing-statements` | List statements (filters `site_day_id`, `contract_id`, `status`) | All roles |
| GET | `/api/billing-statements/{id}` | Get a statement | All roles |
| POST | `/api/billing-statements/{id}/finalize` | `PROVISIONAL` → `FINALIZED`; recomputes the final variant | OperationsDirector |
| POST | `/api/billing-statements/{id}/dispute` | `FINALIZED` → `DISPUTED` (the facility's own coordinator only) | FacilityCoordinator |
| POST | `/api/billing-statements/{id}/resolve-dispute` | `DISPUTED` → `FINALIZED`; `ADJUST` overwrites `final_amount_cents` | OperationsDirector |
| POST | `/api/billing-statements/{id}/invoice` | `FINALIZED` → `INVOICED` | OperationsDirector |
| POST | `/api/billing-statements/{id}/mark-paid` | `INVOICED` → `PAID`; `paid_amount_cents` must equal `net_due_cents` | OperationsDirector |
| POST | `/api/image-studies` | Register a DICOM study for a `COMPLETED` appointment (`QUEUED`) | Technologist |
| GET | `/api/image-studies` | List image studies (filters `appointment_id`, `status`) | All roles |
| GET | `/api/image-studies/{id}` | Get an image study | All roles |
| POST | `/api/image-studies/{id}/transmit` | `QUEUED` → `DELIVERED` within the uplink budget, else `TRANSFER_FAILED` | Technologist |
| POST | `/api/image-studies/{id}/retry` | `TRANSFER_FAILED` → `QUEUED` | Technologist |
| POST | `/api/image-studies/{id}/acknowledge` | `DELIVERED` → `ACKNOWLEDGED`; computes `sla_breached` | ReadingRadiologist |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is a reference index of identifiers and HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SITE_DAY_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TECHNOLOGIST_NOT_FOUND` | 404 Not Found |
| `ERR_STAFFING_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSPORT_LEG_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKLIST_NOT_FOUND` | 404 Not Found |
| `ERR_BREAKDOWN_NOT_FOUND` | 404 Not Found |
| `ERR_ACCREDITATION_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_UNIT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ROUTE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PLAN_NOT_LOCKED` | 409 Conflict |
| `ERR_PLAN_WEEK_CONFLICT` | 409 Conflict |
| `ERR_EMPTY_ROUTE_PLAN` | 409 Conflict |
| `ERR_PLAN_HAS_ACTIVE_DAYS` | 409 Conflict |
| `ERR_SITE_DAY_NOT_BOOKABLE` | 409 Conflict |
| `ERR_SITE_DAY_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_UNIT_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_UNIT_HAS_ACTIVE_DAY` | 409 Conflict |
| `ERR_TRANSPORT_NOT_ARRIVED` | 409 Conflict |
| `ERR_NO_STAFF_ASSIGNED` | 409 Conflict |
| `ERR_OPEN_APPOINTMENTS` | 409 Conflict |
| `ERR_CHECKLIST_INCOMPLETE` | 409 Conflict |
| `ERR_CHECKLIST_EXISTS` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_STATEMENT_NOT_FINALIZABLE` | 409 Conflict |
| `ERR_STUDY_NOT_TRANSFERRABLE` | 409 Conflict |
| `ERR_BREAKDOWN_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_RESCHEDULE_SOURCE_INVALID` | 409 Conflict |
| `ERR_RESCHEDULE_TARGET_INVALID` | 409 Conflict |
| `ERR_DOSE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DOSE_NOT_APPLICABLE` | 422 Unprocessable Entity |
| `ERR_PAD_POWER_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_MODALITY_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_MODALITY_CERT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CONTRACT_FACILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FACILITY_MISMATCH` | 403 Forbidden |
| `ERR_TECHNOLOGIST_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_TECHNOLOGIST_NOT_STAFFED` | 422 Unprocessable Entity |
| `ERR_DRIVE_TIME_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SERVICE_DATE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_SERVICE_DATE_OUTSIDE_PLAN_WEEK` | 422 Unprocessable Entity |
| `ERR_WINDOW_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_SLOT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_UNIT_DAY_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STAFFING_DATE_CONFLICT` | 409 Conflict |
| `ERR_ACCREDITATION_NOT_VALID` | 422 Unprocessable Entity |
| `ERR_SCAN_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
