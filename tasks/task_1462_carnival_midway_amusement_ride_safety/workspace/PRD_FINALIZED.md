# Carnival Midway Ride Safety API — Product Requirements Document

## 1. Introduction

Traveling carnivals compress an extraordinary amount of regulatory risk into a few weeks: rides are assembled by transient crews, inspected by a small pool of state inspectors, operated by seasonal staff, and ridden by thousands of guests a day — often in shifting weather. A state ride-safety program must certify that every ride on the midway is assembled correctly, inspected on schedule, operated by certified staff, and shut down promptly when wind or incidents demand it, all while the show side sells tickets, manages queues, and reconciles every cent of revenue each night.

This document specifies the Carnival Midway Ride Safety API, the system of record for that program. It governs the full engagement lifecycle: registering a fair and its ride inventory, scheduling state inspections and deciding the operating permit (with segregation of duties between the inspector who inspects and the inspector who approves), hiring and certifying midway staff, running the daily pre-opening checklist gate before gates open, selling and redeeming tickets and wristbands under capacity and rider-restriction rules, enforcing weather and incident shutdown cascades, and settling each day's revenue with breakage analysis before the season is torn down and archived. All collections are flat peer resources mounted under the `/midway` path prefix and joined by identifier references in request bodies and query parameters. Every date-sensitive rule in the program reads a controllable logical clock (§2.4), so an entire season can be driven deterministically from setup through archival.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, the logical clock, resource metadata, concurrency control, monetary precision, collection filtering, ride posture model, and the fixed order in which requests are validated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. Missing or blank headers are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles, spelled precisely as follows: `StateProgramAdmin`, `StateInspector`, `FairManager`, `RideOperator`, `TicketClerk`, and `CrewMember`. Each endpoint admits a declared set of roles (§4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403). All six roles may call every read (GET) endpoint.

Identity resolution differs per role, and it is what ties `X-User-ID` to resource ownership:

- When `X-User-Role` is `StateProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; the role exists to seed and administer program data (fairs, inspectors, certifications, the logical clock).
- When `X-User-Role` is `StateInspector`, `X-User-ID` is the `id` of the acting `Inspector`, and that inspector record must have `active` equal to true; an inactive inspector calling any endpoint is rejected with `ERR_FORBIDDEN`. Ownership checks compare `X-User-ID` to inspector foreign keys such as an appointment's assigned inspector.
- When `X-User-Role` is `FairManager`, `RideOperator`, `TicketClerk`, or `CrewMember`, `X-User-ID` is the `id` of the acting `StaffMember`. The staff record must have `status` `ACTIVE`, must carry the function mapped to the role — `SUPERVISOR` for `FairManager`, `OPERATOR` for `RideOperator`, `CLERK` for `TicketClerk`, `CREW` for `CrewMember` — and its `fair_id` must match the fair of the endpoint's primary resource (the resource addressed by the path; for collection creates, the fair named by the body's `fair_id` or implied by a referenced ride or product). Any failure of this scoping — wrong function, a `RELEASED` staff member, or a cross-fair call — is `ERR_FORBIDDEN`. Ownership checks on resources that record a staff foreign key (a checklist's performer, a cycle's operator, a shift's assignee, a sale's clerk) compare that foreign key to `X-User-ID`.

One boundary is deliberate: entity scoping authenticates the caller against the primary resource's fair only. When a request references two resources that belong to different fairs (for example, a wristband sold at one fair presented at a ride of another), that disagreement is not decided at authentication — it is a referential-integrity failure surfaced later as `ERR_CROSS_FAIR_REFERENCE` (see §2.10).

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Program Logical Clock

The server maintains its own logical clock, and every date or timestamp comparison in this document — season windows, certification validity, appointment windows, "today" checks, decision and completion stamps — reads this clock, never the host machine's wall clock. At startup the logical clock is exactly `2026-08-01T00:00:00Z`. A `StateProgramAdmin`-only test-driving capability moves the clock to a supplied `to_iso8601` instant (ISO 8601 UTC) and returns the resulting `current_utc`; the clock never falls back to wall-clock time on its own and is never rewound below the startup default. Timestamps described throughout §3 as "the current logical clock" (completion stamps, release stamps, decision stamps, clearance stamps) are taken from this clock.

### 2.5. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations produced by cascades and derived-field recomputation.

One entity is deliberately exempt: **WeatherObservation** records are append-only and carry only `id` and `created_at` — both `updated_at` and `version` are absent from them. All other entities carry the full set.

### 2.6. Optimistic Concurrency Control

Three write operations require a non-optional expected-version field, and reject the request when the client's last observed version no longer matches the parent entity's current `version`:

- Creating a crew shift (`POST /midway/crew-shifts`) requires `expected_staff_version` carrying the client's last observed `version` of the target `StaffMember`. A mismatch is rejected with `ERR_STALE_STAFF_VERSION` (HTTP 412). Shift creation and the staff-release cascade both advance the staff row's version, so a client booking from an out-of-date staff snapshot would otherwise schedule against a schedule it has not observed.
- Approving a permit (`POST /midway/permits/{id}/approve`) requires `expected_fair_version` carrying the client's last observed `version` of the parent `Fair`. A mismatch is rejected with `ERR_STALE_FAIR_VERSION` (HTTP 412). Ride registration and the request-permit transition both advance the fair's version, so an approver working from a stale fair snapshot would certify an out-of-date ride inventory.
- Countersigning a daily checklist (`POST /midway/daily-checklists/{id}/countersign`) requires `expected_checklist_version` carrying the countersigner's last observed `version` of the `DailyChecklist`. A mismatch is rejected with `ERR_STALE_CHECKLIST_VERSION` (HTTP 412). Submission and rejection both advance the checklist version, so a countersigner reviewing a stale copy would otherwise attest `items_passed` values that have since been edited.

Endpoints not named above take no expected-version field at all.

### 2.7. Money, Cents, and Rounding

All monetary values are integer cents; no fractional cents, floats, or decimal strings appear anywhere in the API. Where a computation produces a fractional cent — the discounted per-credit tier prices, the percentage service fee, and the per-sale pro-rata revenue recognition — the result is rounded half-up to whole cents at the step the rule prescribes: discounted tier prices are rounded per unit before being multiplied by the tier count (never sum-then-round), the service fee is rounded once on the pre-fee subtotal, and pro-rated revenue is rounded per sale before being summed. Permit fees involve only integer additions and require no rounding at all.

### 2.8. Collections, Filtering, and Cross-Fair Isolation

All resources live in flat peer collections under `/midway`; there are no nested URL hierarchies. Related resources are joined by identifier fields in request bodies and, for reverse lookups, by query-parameter filters on the list endpoints. The filterable attributes per collection are:

- Fairs filter by `status`. Rides filter by `fair_id`, `setup_status`, `license_status`, and `daily_status`. Inspectors filter by `active`.
- Inspection appointments filter by `fair_id`, `inspector_id`, `ride_id`, `scheduled_date`, and `status`. Permits filter by `fair_id`, `status`, and `approved_by_inspector_id`.
- Staff filter by `fair_id` and `status`. Operator certifications filter by `staff_id`, `ride_class`, and `status`. Crew shifts filter by `staff_id`, `fair_id`, `work_date`, `shift_role`, and `status`.
- Operating days filter by `fair_id`, `posture`, and `date`. Daily checklists filter by `ride_id`, `operating_day_id`, `performed_by_staff_id`, `countersigned_by_staff_id`, and `status`.
- Ride cycles filter by `ride_id`, `operating_day_id`, `operator_staff_id`, and `status`. Ride redemptions filter by `wristband_id`, `ride_id`, `operating_day_id`, `ride_cycle_id`, and `status`.
- Ticket products filter by `fair_id`, `kind`, and `active`. Ticket sales filter by `operating_day_id`, `product_id`, `clerk_staff_id`, and `status`.
- Weather observations filter by `operating_day_id`. Incident reports filter by `ride_id`, `operating_day_id`, `reporter_staff_id`, `cleared_by_inspector_id`, `severity`, and `status`.

Cross-fair integrity is a program invariant: a ride belongs to exactly one fair, and any operation that pairs two resources — a checklist or cycle pairing a ride with an operating day, a redemption pairing a wristband with a ride, an appointment pairing a ride with a fair — requires both sides to belong to the same fair. A disagreement is rejected with `ERR_CROSS_FAIR_REFERENCE` (HTTP 422).

### 2.9. Parallel Ride Postures and Cascading State

A ride's condition is tracked on three largely independent axes, because the program treats assembly, licensure, and day-to-day operation as separate questions. The `setup_status` axis is linear: `INSTALLED` to `SETUP_VERIFIED` to `DISMANTLED`. The `license_status` axis begins at `PENDING`, reaches `LICENSED`, and then loops through `SUSPENDED` and back to `LICENSED` as ride audits fail and pass, with `REVOKED` as a terminal exit (a ride is also considered finished when dismantled). The `daily_status` axis cycles within each operating day among `CLOSED`, `OPEN`, `WEATHER_HOLD`, and `INCIDENT_HOLD`.

Cascades cross these axes and cross entity boundaries, and they are immediate — the system reconciles dependent resources in the same breath as the triggering operation rather than awaiting a later sweep. Approving a permit licenses every verified ride of the fair. Completing a ride cycle can suspend a license mid-day, which closes the ride and voids its waiting queue. Recording a wind gust can hold individual rides or the entire fair. Releasing a staff member cancels their future shifts. Closing the gates closes rides, expires queues, and forfeits unredeemed credits. Every entity a cascade touches is a mutation in the sense of §2.5: its `updated_at` is refreshed and its `version` advances by one.

### 2.10. Validation Order and Rejection Sequence

Every request is evaluated against a fixed pipeline of check families, and the first failure stops the pipeline — later families are never consulted. A malformed body therefore surfaces `ERR_INVALID_REQUEST` even when the target resource is also in the wrong state, and a state error masks a safety violation that would otherwise also apply. The families, in evaluation order:

1. **Authentication (all endpoints).** The `X-User-Role` and `X-User-ID` headers must be present and non-blank, else `ERR_UNAUTHENTICATED` (401).
2. **Role authorization (all endpoints).** The role must be admitted by the endpoint, else `ERR_FORBIDDEN` (403).
3. **Entity-backed scoping (all endpoints with entity-backed roles).** The caller's identity must resolve per §2.1 — active staff member with the mapped function on the primary resource's fair, or an active inspector — else `ERR_FORBIDDEN`. Cross-resource fair disagreements between two referenced resources are deliberately not decided here; they surface at family 13.
4. **Path resolution (all endpoints with path parameters).** Path identifiers must resolve, validated left to right; the first unresolvable identifier yields `ERR_NOT_FOUND` (404) before any later segment is examined.
5. **Request shape (all endpoints with a request body).** Required fields present, types and enum membership valid, numeric ranges honored (hours, heights, quantities, capacities), the fair date ordering respected, a wristband sale carrying exactly quantity one, `ride_id` present exactly when an appointment's scope is `RIDE_AUDIT` and absent otherwise, `SERIOUS` and `FATAL` incident reports carrying an `injury_count` of at least one, and no unknown or server-computed fields supplied — any violation yields `ERR_INVALID_REQUEST` (400).
6. **Body foreign keys (all create endpoints with identifier inputs).** Referenced identifiers such as `fair_id`, `ride_id`, `operating_day_id`, `product_id`, `wristband_id`, and `staff_id` must resolve, else `ERR_NOT_FOUND` (404).
7. **State preconditions (all action endpoints).** The target resource's state machine must admit the operation — including ride creation only while the fair is `SETUP`, `PERMIT_REQUESTED`, or `PERMITTED`, and appointment scheduling only while the fair is `PERMIT_REQUESTED` or `PERMITTED` — else the matching 409 error: `ERR_FAIR_INVALID_STATE`, `ERR_PERMIT_INVALID_STATE`, `ERR_INVALID_DAY_POSTURE`, `ERR_RIDE_INVALID_STATE`, `ERR_RIDE_NOT_OPEN`, `ERR_RIDE_NOT_LICENSED`, `ERR_CHECKLIST_INVALID_STATE`, `ERR_CYCLE_INVALID_STATE`, `ERR_SALE_NOT_ACTIVE`, `ERR_REDEMPTION_NOT_VOIDABLE`, `ERR_SHIFT_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`, `ERR_INCIDENT_INVALID_STATE`, `ERR_CERT_INVALID_STATE`, or `ERR_STAFF_INVALID_STATE`.
8. **Safety and compliance (redemption creation; checklist creation, submission, and countersignature; assembly verification and ride resumption; day resumption; permit approval and denial).** Rider height inside the ride's inclusive window, a fully passed checklist, a valid operator certification for the ride's class, season-covering annual certification, wind resume guards, segregation of duties on the permit decision and the checklist countersignature, and a passed fair-wide inspection preceding permit approval — else `ERR_HEIGHT_RESTRICTION`, `ERR_CHECKLIST_INCOMPLETE`, `ERR_CERTIFICATION_MISSING`, `ERR_ANNUAL_CERT_EXPIRED`, `ERR_WIND_ABOVE_LIMIT`, `ERR_PERMIT_APPROVER_CONFLICT`, `ERR_CHECKLIST_COUNTERSIGNER_CONFLICT`, or `ERR_INSPECTION_REQUIRED` (all 422).
9. **Uniqueness and resource conflicts (inspector, operating-day, checklist, crew-shift, and cycle creation).** Duplicate inspector license number, duplicate operating day for the same fair and date, duplicate checklist for the same ride and day, an overlapping crew shift, or a second in-progress cycle for one ride — else `ERR_INSPECTOR_LICENSE_EXISTS`, `ERR_DUPLICATE_OPERATING_DAY`, `ERR_DUPLICATE_CHECKLIST`, `ERR_STAFF_SHIFT_OVERLAP`, or `ERR_CYCLE_IN_PROGRESS` (all 409).
10. **Remaining constraint satisfaction (permit request, appointment creation, day creation, assembly verification and dismantling, sale creation).** At least one assembly-verified ride before a permit can be requested, an eligible inspector available, the day's attendance cap within the midway capacity, a covering crew shift for assembly and teardown work, and a sellable (active) product — else `ERR_NO_VERIFIED_RIDES`, `ERR_INSPECTOR_UNAVAILABLE`, `ERR_CAPACITY_ABOVE_MIDWAY`, `ERR_NO_COVERING_SHIFT`, or `ERR_PRODUCT_INACTIVE` (all 422).
11. **Temporal gates (begin-checklists; crew-shift creation, confirmation, completion, and no-show; appointment creation and completion).** The day must be today to begin checklists, the shift's work date must be current-or-future and inside its season window, the appointment's date must sit inside its scheduling window, and an appointment cannot complete before its scheduled date — else `ERR_DAY_NOT_TODAY`, `ERR_SHIFT_OUT_OF_SEASON`, `ERR_APPOINTMENT_WINDOW_INVALID`, or `ERR_APPOINTMENT_NOT_DUE` (all 422).
12. **Fiscal gates, last among the business rules (redemption creation, ticket-sale creation).** A credit-bearing wristband must hold at least one credit, and the day must have attendance headroom — else `ERR_INSUFFICIENT_CREDITS` or `ERR_DAY_AT_CAPACITY` (both 422).
13. **Cross-aggregate integrity (fair archival and begin-teardown, sale voiding, redemption creation, ride resumption).** All rides dismantled before archival, no active day blocking teardown, no boarded redemptions blocking a void, wristband and ride in the same fair, and no open incidents blocking a resume — else `ERR_RIDES_NOT_DISMANTLED`, `ERR_DAYS_STILL_ACTIVE`, `ERR_SALE_HAS_REDEMPTIONS`, `ERR_CROSS_FAIR_REFERENCE`, or `ERR_INCIDENTS_OPEN` (all 422).

## 3. Business Logic & Workflows

### 3.1. Registering the Engagement: Fairs, Ride Inventory, and Assembly Verification

An engagement begins when a `StateProgramAdmin` registers a **Fair**, supplying its public `name`, the show owner's `operator_company_name`, the fairground `location`, the four season dates — `setup_start_date`, `opening_date`, `closing_date`, and `teardown_end_date` — and the `midway_capacity`, the maximum number of guests permitted on the midway at once. The four dates must form a non-decreasing chain: setup may not begin after opening day, opening may not fall after closing, and closing may not fall after the end of teardown; any violation of that ordering, or a `midway_capacity` below one, is rejected with `ERR_INVALID_REQUEST`. A new fair starts in `SETUP` status and walks a one-way lifecycle through `PERMIT_REQUESTED` and `PERMITTED` to `TEARDOWN` and finally the terminal `ARCHIVED`. The midway capacity also becomes the upper bound for every operating day's attendance cap (§3.4).

With a fair on file, a `FairManager` builds the ride inventory. Each ride is registered against a `fair_id` with a display `name`, the `manufacturer`, `model`, and `serial_number`, a `ride_class` of `KIDDIE`, `FAMILY`, `THRILL`, or `EXTREME`, a `capacity_per_cycle` of at least one rider, a rider height window from `min_rider_height_in` to `max_rider_height_in` (each bound between 20 and 96 inches, with the minimum not above the maximum), the manufacturer wind shutdown limit `wind_limit_mph` (between 5 and 60 mph), the `cycle_inspection_interval` — the number of completed cycles the manufacturer allows between required state ride audits, at least one — and the `annual_cert_expires_on` date of the manufacturer's annual certification. Registration is accepted only while the fair is `SETUP`, `PERMIT_REQUESTED`, or `PERMITTED`; at any other point the attempt is rejected with `ERR_FAIR_INVALID_STATE`. A new ride starts with `setup_status` `INSTALLED`, `license_status` `PENDING`, and `daily_status` `CLOSED`, with both of its counters — `cycles_since_inspection` and `minor_incidents_today` — at zero. Because the permit certifies the ride inventory as it stood when approved, every ride registration also advances the parent fair's `version` by one as an inventory ledger sync.

Before a ride can count toward a permit, a `CrewMember` verifies its assembly, moving `setup_status` from `INSTALLED` to `SETUP_VERIFIED` and advancing the ride's `version`. Four conditions gate the verification, in the pipeline order of §2.10: the fair must be `SETUP` or `PERMIT_REQUESTED` (`ERR_FAIR_INVALID_STATE`); the ride must still be `INSTALLED` (`ERR_RIDE_INVALID_STATE`); the manufacturer annual certification must cover the whole season, meaning `annual_cert_expires_on` falls on or after the fair's `closing_date` (`ERR_ANNUAL_CERT_EXPIRED`); and the caller must hold a covering crew shift — a `CrewShift` whose `shift_role` is `SETUP`, whose `work_date` equals the current date, and whose status is `SCHEDULED` or `CONFIRMED` (`ERR_NO_COVERING_SHIFT`).

### 3.2. State Oversight: Inspectors, Appointments, and the Permit Decision

The state side of the program starts with the inspector registry. A `StateProgramAdmin` registers each **Inspector** with a `full_name` and a state-issued `license_number` that must be unique across all inspectors — a duplicate is rejected with `ERR_INSPECTOR_LICENSE_EXISTS`. An optional `max_daily_inspections` caps the inspector's appointment load per day; when omitted it defaults to 3, and in all cases it must sit between 1 and 8. New inspectors are `active` by default. Deactivating an inspector flips `active` to false, which makes the inspector ineligible for new assignments while leaving their existing appointments untouched.

Inspection demand is expressed as **InspectionAppointments**. A `FairManager` schedules one by supplying the `fair_id`, a `scope` of `FAIR_WIDE` or `RIDE_AUDIT`, the `scheduled_date`, a `start_hour` between 6 and 20, and a `duration_hours` between 1 and 4. A ride-scoped audit must name its `ride_id`, and that ride must belong to the named fair; a fair-wide appointment must not carry a `ride_id` at all. The appointment's `end_hour` is derived as the `start_hour` plus the `duration_hours` and may not exceed 21. The fair must be `PERMIT_REQUESTED` or `PERMITTED` (`ERR_FAIR_INVALID_STATE`), and the `scheduled_date` must fall on or after the current date and on or before the fair's `teardown_end_date` (`ERR_APPOINTMENT_WINDOW_INVALID`). The requester never picks the inspector: the server assigns `inspector_id` automatically, and the appointment enters `SCHEDULED` status.

Assignment considers every inspector and keeps those who are eligible: the inspector is `active`; the number of their appointments on the same date in `SCHEDULED`, `COMPLETED_PASS`, or `COMPLETED_FAIL` status is below their `max_daily_inspections`; and no appointment of theirs on that date in one of those three statuses violates a two-hour travel buffer. The buffer is satisfied when the new appointment's end (its `start_hour` plus `duration_hours`) plus two hours is at or before the existing appointment's start hour, or when the existing appointment's `end_hour` plus two hours is at or before the new appointment's start hour; otherwise the two appointments conflict and the inspector is ineligible. A `CANCELLED` appointment occupies no capacity and frees its slot. Eligible inspectors are ranked by their same-date appointment count in ascending order, ties broken by inspector seniority — the earlier `created_at` first — and the first inspector in that ranking receives the assignment. An empty pool is rejected with `ERR_INSPECTOR_UNAVAILABLE`.

Completion belongs to the assigned inspector alone. A `StateInspector` completes a `SCHEDULED` appointment by recording an `outcome` of PASS or FAIL, with optional free-text `findings`; completing from any other status is `ERR_APPOINTMENT_INVALID_STATE`, a caller whose `X-User-ID` is not the appointment's `inspector_id` is `ERR_FORBIDDEN`, and completing before the `scheduled_date` has arrived is `ERR_APPOINTMENT_NOT_DUE`. A ride-scoped audit additionally requires the fair to be `PERMITTED` (`ERR_FAIR_INVALID_STATE`). Completion stamps `completed_at` from the current logical clock and lands the appointment in `COMPLETED_PASS` or `COMPLETED_FAIL`. A passed `RIDE_AUDIT` resets the audited ride's `cycles_since_inspection` to zero and moves its `license_status` from `PENDING` or `SUSPENDED` to `LICENSED`. A failed `FAIR_WIDE` inspection is remembered: it is counted as a reinspection failure in the final permit fee. A `FairManager` may also cancel a `SCHEDULED` appointment, moving it to `CANCELLED`.

Once at least one ride stands verified, a `FairManager` requests the permit, which moves the fair from `SETUP` to `PERMIT_REQUESTED`, advances the fair's `version`, and creates the **Permit** in `PENDING` status. Requesting with zero `SETUP_VERIFIED` rides is rejected with `ERR_NO_VERIFIED_RIDES`; requesting from any fair status other than `SETUP` is `ERR_FAIR_INVALID_STATE`. The request freezes the permit's `estimated_fee_cents`.

The permit fee is a tiered computation over qualifying rides — the fair's rides whose `setup_status` is `SETUP_VERIFIED` at evaluation time, whatever their license posture; `INSTALLED` and `DISMANTLED` rides never qualify. The fee starts from a 25,000-cent base, adds a per-ride class rate for each qualifying ride — 5,000 cents for `KIDDIE`, 9,000 for `FAMILY`, 14,000 for `THRILL`, and 20,000 for `EXTREME` — and then adds a 7,500-cent reinspection surcharge for each of the fair's `FAIR_WIDE` appointments that ended `COMPLETED_FAIL`. A hard ceiling of 200,000 cents is applied last, after the surcharges. Two variants exist. The *estimated* variant is evaluated at request time over the qualifying ride set as it then stands, with the failure count fixed at zero; it is frozen into `estimated_fee_cents` and never recomputed. The *final* variant is re-evaluated at approval time over the qualifying ride set as it then stands, with the actual failure count; it is stored in `final_fee_cents` together with `billable_ride_count` (the number of qualifying rides at decision time) and `reinspection_failure_count` (the number of failed fair-wide inspections at decision time). Until the permit is decided, `final_fee_cents`, `billable_ride_count`, and `reinspection_failure_count` are null.

Approval and denial belong to a `StateInspector`, and both carry the program's central segregation-of-duties rule. Approval requires the permit to be `PENDING` (`ERR_PERMIT_INVALID_STATE`), requires the OCC handshake of §2.6 — `expected_fair_version` matching the fair's current `version`, else `ERR_STALE_FAIR_VERSION` — requires evidence that the fair passed inspection since the permit was opened, namely a `FAIR_WIDE` appointment in `COMPLETED_PASS` whose `completed_at` is at or after the permit's `created_at` (`ERR_INSPECTION_REQUIRED`), and requires that the approving caller is not the inspector who conducted the latest such passed fair-wide inspection (`ERR_PERMIT_APPROVER_CONFLICT`). Approving computes the final fee fields, records the caller in `approved_by_inspector_id`, stamps `decided_at` from the logical clock, moves the permit to `APPROVED`, and cascades: the fair moves `PERMIT_REQUESTED` to `PERMITTED`, every ride of the fair with `setup_status` `SETUP_VERIFIED` has its `license_status` moved from `PENDING` to `LICENSED`, and the fair's `version` advances.

Denial mirrors the approval gate with equal rigor: the permit must be `PENDING`, and the same segregation rule is evaluated against the inspector of the latest passed fair-wide inspection whenever one exists — that inspector may not deny their own inspected fair either (`ERR_PERMIT_APPROVER_CONFLICT`). The denying inspector supplies a `reason`, which is recorded in the permit's `denial_reason`; `decided_at` is stamped; the permit lands in `DENIED`; and the fair loops back from `PERMIT_REQUESTED` to `SETUP` with its `version` advancing, leaving every ride's `setup_status` as it was and every license `PENDING` so the operator can remediate and request again. While a permit remains `PENDING`, its `approved_by_inspector_id`, `denial_reason`, and `decided_at` are all null.

### 3.3. Staffing the Show: Hiring, Operator Certifications, and Crew Shifts

Every midway worker is a **StaffMember** of exactly one fair. A `StateProgramAdmin` seeds the first supervisor for each fair; after that, the `FairManager` hires the rest. Hiring supplies the `fair_id`, the worker's `full_name`, and their `functions` — a non-empty subset of `OPERATOR`, `CLERK`, `CREW`, and `SUPERVISOR` — which permanently gates which staff-backed roles (§2.1) the worker may act in. A new staff member is `ACTIVE` with a null `released_at`.

Releasing a worker is a `FairManager` action on an `ACTIVE` staff member — releasing someone already `RELEASED` is `ERR_STAFF_INVALID_STATE`. Release stamps `released_at` from the logical clock, moves the worker to `RELEASED`, and triggers a compensation cascade: every `CrewShift` of that worker in `SCHEDULED` or `CONFIRMED` status whose `work_date` is the current date or later is moved to `CANCELLED`, while past-dated shifts are left untouched for the record.

Ride operators must additionally hold state-issued **OperatorCertifications**. A `StateProgramAdmin` issues one by naming the `staff_id` — the worker must carry the `OPERATOR` function — a `ride_class` (`KIDDIE`, `FAMILY`, `THRILL`, or `EXTREME`), the `issued_on` date, and an `expires_on` date that must fall strictly after `issued_on`. A certification is `ACTIVE` upon issuance and may later be moved to `REVOKED` by a `StateProgramAdmin` or a `StateInspector`; revoking an already-`REVOKED` certification is `ERR_CERT_INVALID_STATE`. A certification never carries a stored expired state: validity is evaluated at enforcement time, and a certification is valid exactly when its status is `ACTIVE` and its `expires_on` is on or after the current date. Wherever the program demands a certified operator — checklist creation and submission (§3.4) and cycle operations (§3.6) — a caller without a valid certification for the ride's class, or whose staff record has been released, is rejected with `ERR_CERTIFICATION_MISSING`.

Setup and teardown labor is scheduled as **CrewShifts**. A `FairManager` books a shift by naming the `staff_id`, the `work_date`, a `start_hour` between 0 and 23, an `end_hour` between 1 and 24, a `shift_role` of `SETUP`, `OPERATIONS`, or `TEARDOWN`, and the `expected_staff_version` handshake of §2.6 — a stale staff snapshot is rejected with `ERR_STALE_STAFF_VERSION`. The worker must be `ACTIVE` and carry the `CREW` function, and the shift's `fair_id` is denormalized from the worker's own fair at creation. The start hour must precede the end hour, the shift may not exceed twelve hours (`ERR_INVALID_REQUEST`), and shifts occupy the half-open interval from their start hour up to but not including their end hour, so back-to-back shifts whose endpoints merely touch do not conflict. A new shift that intersects an existing `SCHEDULED`, `CONFIRMED`, or `COMPLETED` shift of the same worker on the same date is rejected with `ERR_STAFF_SHIFT_OVERLAP`. The `work_date` must be the current date or later and must fall inside the role's season window — `SETUP` shifts run from `setup_start_date` through the day before `opening_date`; `OPERATIONS` shifts run from `opening_date` through `closing_date`, both inclusive; `TEARDOWN` shifts run from the day after `closing_date` through `teardown_end_date`, both inclusive — and a date in the past or outside the window is rejected with `ERR_SHIFT_OUT_OF_SEASON`. Booking a shift is itself a mutation of the staff ledger: it advances the staff member's `version` by one.

A shift's own lifecycle begins at `SCHEDULED`. The assigned crew member — and only that worker, by `X-User-ID` against the shift's `staff_id` (`ERR_FORBIDDEN`) — confirms their own shift, moving it to `CONFIRMED`, provided the `work_date` has not already passed (`ERR_SHIFT_OUT_OF_SEASON`). A `FairManager` marks a `CONFIRMED` shift `COMPLETED` once its date has arrived, marks a `SCHEDULED` or `CONFIRMED` shift `NO_SHOW` on or after its date (both gated by `ERR_SHIFT_OUT_OF_SEASON` on the date comparisons), and cancels a `SCHEDULED` or `CONFIRMED` shift outright to `CANCELLED`. Every transition requires the shift to be in the status the action expects, else `ERR_SHIFT_INVALID_STATE`; `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal.

### 3.4. The Operating Day and the Pre-Opening Checklist Gate

Once the fair is `PERMITTED`, a `FairManager` schedules **OperatingDays** by naming the `fair_id`, the `date`, and the day's `max_attendance` guest cap. The fair must indeed be `PERMITTED` (`ERR_FAIR_INVALID_STATE`); the date must be unique within the fair (`ERR_DUPLICATE_OPERATING_DAY`), must fall between `opening_date` and `closing_date` inclusive, and must not be in the past; the cap must be at least one and no greater than the fair's `midway_capacity` (`ERR_CAPACITY_ABOVE_MIDWAY`). A new day enters the `SCHEDULED` posture with `attendance_count` at zero and all of its settlement fields — `gross_sales_cents`, `voided_cents`, `projected_revenue_cents`, `recognized_revenue_cents`, `breakage_cents`, and `reconciliation_flagged` — still null.

On the morning of the day itself, the `FairManager` begins the checklist phase, moving the posture from `SCHEDULED` to `CHECKLIST_PHASE`. Beginning from any other posture is `ERR_INVALID_DAY_POSTURE`, and beginning on any date other than the day's own `date` — as read from the logical clock — is `ERR_DAY_NOT_TODAY`. The phase change also resets every ride of the fair: each ride's `minor_incidents_today` counter returns to zero for the new day.

During the checklist phase, a `RideOperator` opens the day's pre-opening **DailyChecklist** for each ride by submitting the `ride_id`, the `operating_day_id` (the day must belong to the same fair as the ride), and the `items_total` count of inspection items, at least one. One checklist per ride per day is allowed; a second is rejected with `ERR_DUPLICATE_CHECKLIST`, and a ride whose license is not `LICENSED` cannot be checked in at all (`ERR_RIDE_NOT_LICENSED`). The opener must also hold a valid operator certification for the ride's `ride_class` (§3.3), else `ERR_CERTIFICATION_MISSING`; per the §2.10 pipeline this safety gate is evaluated after the license and day-posture state checks and before the duplicate-checklist check. The opener is recorded as `performed_by_staff_id` from the caller's `X-User-ID`, `countersigned_by_staff_id` remains null, and the checklist enters `DRAFT` with `items_passed` still null and `rejection_reason` null.

Submission belongs to the performer alone: the caller must be the `performed_by_staff_id` (`ERR_FORBIDDEN`), the checklist must be `DRAFT` (`ERR_CHECKLIST_INVALID_STATE`), the day must still be in `CHECKLIST_PHASE` (`ERR_INVALID_DAY_POSTURE`), and the caller must hold a valid certification for the ride's `ride_class` (`ERR_CERTIFICATION_MISSING`). The performer reports `items_passed`, which must equal `items_total` — anything short is rejected with `ERR_CHECKLIST_INCOMPLETE` — and the checklist moves to `SUBMITTED`, advancing its `version`.

Countersignature belongs to a `FairManager` and enforces segregation of duties: the countersigner must not be the performer (`ERR_CHECKLIST_COUNTERSIGNER_CONFLICT`), the checklist must be `SUBMITTED` (`ERR_CHECKLIST_INVALID_STATE`), and the `expected_checklist_version` handshake of §2.6 must match (`ERR_STALE_CHECKLIST_VERSION`). The countersigner is recorded in `countersigned_by_staff_id`, the checklist moves to the terminal `COUNTERSIGNED`, and its `version` advances. Countersignature doubles as a late-clearance path: if the day's gates are already open — posture `OPEN` — and the ride's license is `LICENSED`, the countersignature moves that ride's `daily_status` from `CLOSED` to `OPEN` on the spot. Alternatively, a `FairManager` rejects a `SUBMITTED` checklist back to `DRAFT`, supplying a `reason`; rejection nulls both `items_passed` and `countersigned_by_staff_id`, records the `rejection_reason`, advances the `version`, and lets the performer correct and resubmit.

When every ride is cleared, the `FairManager` opens the gates, moving the day from `CHECKLIST_PHASE` to `OPEN`. Opening is gated by a compound condition: every ride of the fair that is both `SETUP_VERIFIED` and `LICENSED` must hold a `COUNTERSIGNED` checklist for this day, else the opening is rejected with `ERR_RIDES_NOT_CLEARED`. Each such cleared ride's `daily_status` moves from `CLOSED` to `OPEN` with the gates.

### 3.5. Midway Commerce: Products, Tiered Pricing, and Ticket Sales

Sellable inventory is configured as **TicketProducts** by the `FairManager`: the `fair_id`, a display `name`, a `kind` of `RIDE_TICKET`, `CREDIT_BUNDLE`, or `WRISTBAND`, and a `base_price_cents` of at least one cent. Products are `active` by default; deactivating one flips `active` to false, and an inactive product can no longer be sold (`ERR_PRODUCT_INACTIVE`). The meaning of the base price depends on the kind: per ticket for a `RIDE_TICKET`, per credit for a `CREDIT_BUNDLE`, and a flat price for a `WRISTBAND`.

Sales happen only while the day's gates are open. A `TicketClerk` sells one guest instrument by naming the `product_id` — the product must belong to the same fair as the operating day — the `operating_day_id`, the guest's `holder_height_in` (between 20 and 96 inches, recorded for later rider-restriction enforcement), and the `quantity`. A day whose posture is not `OPEN` rejects the sale with `ERR_INVALID_DAY_POSTURE`. The quantity is the number of credits for a `CREDIT_BUNDLE` (at least one) or the number of tickets for a `RIDE_TICKET` (at least one), and it must be exactly one for a `WRISTBAND` (`ERR_INVALID_REQUEST`). Capacity is enforced at the till: if the day's `attendance_count` has already reached `max_attendance`, the sale is rejected with `ERR_DAY_AT_CAPACITY` — the sale that brings attendance exactly to the cap still succeeds, and the next one fails. A successful sale records the clerk in `clerk_staff_id`, enters `ACTIVE` status, and immediately adds one to the day's `attendance_count`.

Pricing composes three computed amounts on every sale: `subtotal_cents`, `service_fee_cents`, and `total_charged_cents`. The subtotal depends on the product kind. For a `RIDE_TICKET` it is the base price times the quantity. For a `WRISTBAND` it is the flat base price. For a `CREDIT_BUNDLE` it follows a marginal (progressive) tier schedule, never an average rate: the first nine credits are each priced at the full base price; the next fifteen credits — the tenth through the twenty-fourth — are each priced at nine-tenths of the base price, with that per-credit price rounded half-up to whole cents before being multiplied by the tier count; and every credit beyond the twenty-fourth is each priced at eight-tenths of the base price, likewise rounded half-up per credit before multiplying. The subtotal is the sum of the three tier line amounts, each computed from a pre-rounded unit price.

The service fee is then six percent of the pre-fee subtotal, rounded half-up to whole cents, but never less than fifty cents. The evaluation order is pinned: the fee is computed strictly on the pre-fee subtotal, because defining it on the grand total would be circular. The `total_charged_cents` is the subtotal plus the service fee.

A sale also carries its credit ledger. A `WRISTBAND` sale is marked `is_unlimited` true — unlimited instruments never debit credits, and their `credits_granted`, `credits_remaining`, `credits_redeemed`, and `credits_forfeited` are all null. For the credit-bearing kinds (`RIDE_TICKET` and `CREDIT_BUNDLE`), `credits_granted` equals the `quantity`, `credits_remaining` starts at the granted amount and is debited only at boarding time (§3.6), `credits_redeemed` starts at zero and nets boardings against refunds, and `credits_forfeited` starts at zero until close-gates (§3.8) sweeps whatever remains.

Voiding is a same-day operation by a `TicketClerk`, allowed only while the day's posture is `OPEN` (`ERR_INVALID_DAY_POSTURE`). The sale must be `ACTIVE` — voiding a `VOIDED` or `EXPIRED` sale is `ERR_SALE_NOT_ACTIVE` — and no redemption on that wristband may currently be boarded: if any of its redemptions is `REDEEMED`, the void is rejected with `ERR_SALE_HAS_REDEMPTIONS`. A successful void moves the sale to `VOIDED`, moves that sale's still-`QUEUED` redemptions to `VOIDED`, subtracts one from the day's `attendance_count`, and leaves the money for the night's tally — the voided value surfaces in the day's `voided_cents` at close-gates.

### 3.6. Queues, Boarding, and Ride Cycles

A guest joins a ride's queue when a `RideOperator` presents their wristband, creating a **RideRedemption** from the `wristband_id` — the ticket sale the guest is holding — and the `ride_id`. The wristband's sale must be `ACTIVE` (`ERR_SALE_NOT_ACTIVE`), the sale's operating day must currently be `OPEN` (`ERR_INVALID_DAY_POSTURE`), the ride's `daily_status` must be `OPEN` (`ERR_RIDE_NOT_OPEN`), and the wristband and the ride must belong to the same fair (`ERR_CROSS_FAIR_REFERENCE`). Rider restrictions bite here: the guest's `holder_height_in`, recorded at sale time, must fall inside the ride's inclusive window from `min_rider_height_in` to `max_rider_height_in`, else `ERR_HEIGHT_RESTRICTION`; and a credit-bearing wristband must hold at least one remaining credit, else `ERR_INSUFFICIENT_CREDITS` (unlimited wristbands pass this gate unconditionally). The new redemption copies its `operating_day_id` from the wristband's sale, receives the next `queue_position` for its ride and day — a per-ride-and-day ordinal that starts at one and increments with each new entry, so ties are impossible — has no `ride_cycle_id` yet, and enters `QUEUED`.

Ride operation proceeds in **RideCycles**. A `RideOperator` opens a cycle for a ride and operating day of the same fair; the operator must hold a valid certification for the ride's class (`ERR_CERTIFICATION_MISSING`), the ride must be `OPEN` (`ERR_RIDE_NOT_OPEN`), and no other cycle for the same ride may be in `LOADING` or `RUNNING` — a second in-progress cycle is `ERR_CYCLE_IN_PROGRESS`. The cycle records the caller in `operator_staff_id`, receives the next `sequence_number` for its ride and day (an ordinal starting at one), starts with a `rider_count` of zero, and enters `LOADING`.

Boarding fills the open cycle from the queue in strict first-in-first-out order by `queue_position`, considering only `QUEUED` redemptions that match the cycle's ride and day. Boarding stops as soon as the cycle's `rider_count` reaches the ride's `capacity_per_cycle`; candidates beyond that point stay `QUEUED` for the next cycle. Each candidate is evaluated in turn: an unlimited wristband boards with no credit movement; a credit-bearing wristband with at least one remaining credit boards and is debited — `credits_remaining` down one, `credits_redeemed` up one; a credit-bearing wristband with nothing left is moved to `VOIDED` on the spot, skipped without consuming a seat, and selection continues. Each boarded guest's redemption becomes `REDEEMED` with its `ride_cycle_id` set to the cycle, and the cycle's `rider_count` rises by one per boarding. An empty queue is not an error — the boarding call simply succeeds with the count unchanged.

Dispatch moves a `LOADING` cycle to `RUNNING` and is restricted to the cycle's own operator (`ERR_FORBIDDEN`); dispatching from any other status is `ERR_CYCLE_INVALID_STATE`, dispatching an empty cycle is `ERR_CYCLE_EMPTY`, and dispatching is impossible once the ride has left `OPEN` (`ERR_RIDE_NOT_OPEN`). Completion moves a `RUNNING` cycle to `COMPLETED`, again operator-only (`ERR_FORBIDDEN`, `ERR_CYCLE_INVALID_STATE` otherwise), and drives the program's deepest cascade: the ride's `cycles_since_inspection` rises by one, and the moment that counter reaches the manufacturer `cycle_inspection_interval`, the ride's `license_status` moves from `LICENSED` to `SUSPENDED`; suspension in turn moves the ride's `daily_status` from `OPEN` or `WEATHER_HOLD` to `CLOSED`, and every `QUEUED` redemption of that ride for the day is moved to `VOIDED` with no credit movement, since a queued entry has never been debited. The ride then stays suspended until a passed `RIDE_AUDIT` (§3.2) re-licenses it and resets the counter to zero.

Aborting a cycle — from `LOADING` or `RUNNING` alike, operator-only, otherwise `ERR_CYCLE_INVALID_STATE` — lands it in `ABORTED` and refunds everyone aboard: each `REDEEMED` redemption on the cycle moves to `VOIDED`, each credit-bearing wristband's `credits_redeemed` drops by one and `credits_remaining` rises by one, and the cycle's `rider_count` returns to zero. The same compensation applies whether the cycle was still loading or already running.

Individual redemptions can also be voided by a `RideOperator` or a `TicketClerk`. A `QUEUED` redemption voids freely. A `REDEEMED` redemption may be voided only while its cycle is still `LOADING`, and that void carries the same per-guest refund — `credits_redeemed` down one, `credits_remaining` up one, and the cycle's `rider_count` down one. Any other combination — a redemption already `VOIDED` or `EXPIRED`, or a `REDEEMED` one whose cycle has left `LOADING` — is rejected with `ERR_REDEMPTION_NOT_VOIDABLE`. Like sales, voids are same-day operations gated on the day's `OPEN` posture (`ERR_INVALID_DAY_POSTURE`). Throughout, the cycle's `rider_count` is an invariant — the count of its currently `REDEEMED` redemptions — maintained by boarding, voiding, and aborting alike.

### 3.7. Weather Holds and Incident Response

Wind is the midway's standing adversary. A `FairManager` or `RideOperator` records a **WeatherObservation** by naming the `operating_day_id`, the observed sustained `wind_speed_mph` (between 0 and 200), and an optional `note`. Observations are accepted while the day's posture is `CHECKLIST_PHASE`, `OPEN`, or `WEATHER_HOLD` (`ERR_INVALID_DAY_POSTURE` otherwise) and are append-only records carrying only `id` and `created_at` (§2.5).

Each new reading triggers the wind sweep against the rides of that day's fair. The ride hold rule: every ride whose `daily_status` is `OPEN` and whose own `wind_limit_mph` is met or exceeded by the reading moves to `WEATHER_HOLD` — the boundary is inclusive, so a reading exactly equal to a ride's limit holds that ride. The fair closure rule: when the reading reaches 45 mph and the day's posture is `OPEN`, the day itself moves to `WEATHER_HOLD` and every `OPEN` ride moves to `WEATHER_HOLD` regardless of per-ride limits. Weather holds are merciful to the queue: `QUEUED` redemptions are preserved so riders can wait out the hold.

Recovery is deliberately harder than shutdown — a hysteresis keeps a gusty day from flapping a ride back and forth across its limit. Resuming a single ride from `WEATHER_HOLD` is a `FairManager` action requiring the day's posture to be `OPEN` (`ERR_INVALID_DAY_POSTURE`), the ride to be `LICENSED` (`ERR_RIDE_NOT_LICENSED`), and the latest observation of the day — the one with the greatest `created_at` — to read at least 3 mph under the ride's `wind_limit_mph`, that is, wind at or below the limit minus three for these integer readings (`ERR_WIND_ABOVE_LIMIT`); a successful resume moves the ride back to `OPEN` and advances its `version`. Resuming the whole day moves the posture from `WEATHER_HOLD` back to `OPEN` and requires the latest observation to read at or below 39 mph (`ERR_WIND_ABOVE_LIMIT`); day resumption deliberately leaves every ride in `WEATHER_HOLD`, and each ride then reopens individually through the per-ride resume.

Incidents are filed by a `FairManager` or `RideOperator` against a ride and an operating day of the same fair, while the day's posture is `OPEN` or `WEATHER_HOLD` (`ERR_INVALID_DAY_POSTURE` otherwise). The report carries a `severity` of `NEAR_MISS`, `MINOR`, `SERIOUS`, or `FATAL`, an `injury_count` of zero or more — `SERIOUS` and `FATAL` reports must record at least one injury (`ERR_INVALID_REQUEST`) — and a free-text `description`. The filer is recorded in `reporter_staff_id` from `X-User-ID`, and the report enters `FILED` status.

Severity drives an escalation ladder at filing time. A `NEAR_MISS` is informational: no counter moves. A `MINOR` report increments the ride's `minor_incidents_today`, and when that counter reaches three for the current operating date — the threshold is inclusive, so the third minor incident of the day triggers while the second does nothing — a ride whose `daily_status` is `OPEN` or `WEATHER_HOLD` moves to `INCIDENT_HOLD`, with its license untouched so the ride can be cleared and resumed the same day. A `SERIOUS` report moves the ride's `license_status` from `LICENSED` to `SUSPENDED` and moves the `daily_status` of an `OPEN` or `WEATHER_HOLD` ride to `INCIDENT_HOLD`, preserving its queued redemptions. A `FATAL` report moves the license from `LICENSED` to `REVOKED`, moves the ride's `daily_status` to `CLOSED` from `OPEN`, `WEATHER_HOLD`, or `INCIDENT_HOLD`, and voids every `QUEUED` redemption of that ride for the day.

Resolution belongs to a `StateInspector`, acting only on `FILED` reports (`ERR_INCIDENT_INVALID_STATE`). Clearing a report records the caller in `cleared_by_inspector_id`, stamps `cleared_at` from the logical clock, moves the report to `CLEARED`, and then relaxes the ride: if no other report for the same ride and day remains in `FILED` or `SHUTDOWN_ORDERED`, the ride's `daily_status` moves from `INCIDENT_HOLD` to `CLOSED`. Ordering a shutdown instead moves the report to `SHUTDOWN_ORDERED` and fires the heaviest cascade: the ride's `license_status` moves from `LICENSED` or `SUSPENDED` to `REVOKED`, its `daily_status` moves to `CLOSED` from `OPEN`, `WEATHER_HOLD`, or `INCIDENT_HOLD`, and every `QUEUED` redemption of the ride for the day is voided. Until a report is cleared, `cleared_by_inspector_id` and `cleared_at` are null.

A ride held for incidents can be reopened the same day once its reports are resolved: the incident-hold resume — again a `FairManager` action — requires the day's posture `OPEN` (`ERR_INVALID_DAY_POSTURE`), the ride `LICENSED` (`ERR_RIDE_NOT_LICENSED`), and no report for that ride and day remaining in `FILED` or `SHUTDOWN_ORDERED` (`ERR_INCIDENTS_OPEN`), and moves the ride back to `OPEN` with a version advance. Attempting any resume from a ride that is not in a hold state at all is rejected with `ERR_RIDE_INVALID_STATE`.

### 3.8. Settlement, Teardown, and Archival

The operating day ends when a `FairManager` closes the gates — allowed from either `OPEN` or `WEATHER_HOLD` (`ERR_INVALID_DAY_POSTURE` otherwise) — moving the posture to `CLOSED`. Closing fires the nightly cascade: every ride of the fair whose `daily_status` is `OPEN`, `WEATHER_HOLD`, or `INCIDENT_HOLD` moves to `CLOSED`; every still-`QUEUED` redemption of the day moves to `EXPIRED` with no credit movement, since queued entries were never debited; and every credit-bearing sale still `ACTIVE` forfeits its remaining balance — `credits_forfeited` rises by the full `credits_remaining`, `credits_remaining` falls to zero, and the sale moves to `EXPIRED`.

Closing also computes the night's projected settlement, the forward-looking variant. The `gross_sales_cents` is the sum of `total_charged_cents` over every sale of the day, voided sales included. The `voided_cents` is the same sum restricted to `VOIDED` sales. The `projected_revenue_cents` is the gross minus the voided — it recognizes every non-voided sale at full face value regardless of how many credits were ever redeemed.

Later, a `FairManager` reconciles the `CLOSED` day (any other posture is `ERR_INVALID_DAY_POSTURE`), moving it to the terminal `RECONCILED` and computing the chronological variant of revenue. The sales of the day are processed in `created_at` ascending order, and each contributes: zero if `VOIDED`; its full `total_charged_cents` if it is an unlimited wristband sale, recognized in full at the moment of sale; otherwise — for credit-bearing sales, including `EXPIRED` ones contributing with their final `credits_redeemed` — its full `service_fee_cents` plus its `subtotal_cents` pro-rated by the ratio of `credits_redeemed` to `credits_granted`, with that pro-rated amount rounded half-up to whole cents per sale before any summation. The sum is the `recognized_revenue_cents`. The `breakage_cents` is then the projected revenue minus the recognized revenue — the value of credits that were sold but never redeemed — and `reconciliation_flagged` is set true when the breakage strictly exceeds 1,000 cents, drawing auditor attention to unusual unredeemed balances.

When the season ends, the `FairManager` begins teardown, moving the fair from `PERMITTED` to `TEARDOWN`. Teardown cannot begin before the season is over — the current date must be after the fair's `closing_date` (`ERR_INVALID_REQUEST`) — and no operating day may still be in flight: a day in `CHECKLIST_PHASE`, `OPEN`, `WEATHER_HOLD`, or `CLOSED` blocks the move with `ERR_DAYS_STILL_ACTIVE`, while `SCHEDULED` and `RECONCILED` days do not. The fair's `version` advances.

Teardown crews then dismantle the inventory. Dismantling a ride — a `CrewMember` action — requires the ride `SETUP_VERIFIED` (`ERR_RIDE_INVALID_STATE`), the fair in `TEARDOWN` (`ERR_FAIR_INVALID_STATE`), the ride's `daily_status` `CLOSED` (`ERR_RIDE_INVALID_STATE`), and a covering `TEARDOWN` shift for the caller on the current date in `SCHEDULED` or `CONFIRMED` status (`ERR_NO_COVERING_SHIFT`). Dismantling moves `setup_status` to `DISMANTLED`, moves the `license_status` to `REVOKED` if it is not already there — a dismantled ride cannot hold a license — and advances the ride's `version`.

With every ride of the fair `DISMANTLED` — any straggler blocks the move with `ERR_RIDES_NOT_DISMANTLED` — the `FairManager` archives the fair, moving it from `TEARDOWN` (`ERR_FAIR_INVALID_STATE` from any other status) to the terminal `ARCHIVED`, advancing the fair's `version` one final time.

## 4. Endpoint Definitions

Operations that create a new resource respond with `201 Created` — this includes the permit request, which creates the Permit resource even though it also transitions the fair. Operations that modify an existing resource or drive a state transition respond with `200 OK`. Request bodies, computed fields, side effects, and per-endpoint preconditions are defined by the narratives in §2 and §3; the table below is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/midway/fairs` | Register a midway engagement (status `SETUP`) | StateProgramAdmin |
| GET | `/midway/fairs/{id}` | Read one fair | All roles |
| GET | `/midway/fairs` | List fairs | All roles |
| POST | `/midway/fairs/{id}/request-permit` | Open a `PENDING` permit with the estimated fee; `SETUP` → `PERMIT_REQUESTED` | FairManager |
| POST | `/midway/fairs/{id}/begin-teardown` | `PERMITTED` → `TEARDOWN` once no day is active and the season has ended | FairManager |
| POST | `/midway/fairs/{id}/archive` | `TEARDOWN` → `ARCHIVED` once all rides are `DISMANTLED` | FairManager |
| POST | `/midway/rides` | Register a ride in the fair inventory (`INSTALLED`/`PENDING`/`CLOSED`) | FairManager |
| GET | `/midway/rides/{id}` | Read one ride | All roles |
| GET | `/midway/rides` | List/filter rides | All roles |
| POST | `/midway/rides/{id}/verify-assembly` | Setup crew verifies assembly; `INSTALLED` → `SETUP_VERIFIED`; requires covering `SETUP` shift today | CrewMember |
| POST | `/midway/rides/{id}/dismantle` | Teardown crew dismantles; `SETUP_VERIFIED` → `DISMANTLED` and license `REVOKED`; requires covering `TEARDOWN` shift today | CrewMember |
| POST | `/midway/rides/{id}/resume` | Reopen a ride from `WEATHER_HOLD` or `INCIDENT_HOLD` with per-hold guards | FairManager |
| POST | `/midway/inspectors` | Register a state inspector | StateProgramAdmin |
| GET | `/midway/inspectors/{id}` | Read one inspector | All roles |
| GET | `/midway/inspectors` | List/filter inspectors | All roles |
| POST | `/midway/inspectors/{id}/deactivate` | Deactivate an inspector (ineligible for new assignments; existing appointments unaffected) | StateProgramAdmin |
| POST | `/midway/inspection-appointments` | Schedule an inspection; the server auto-assigns an inspector by buffer and daily-cap eligibility | FairManager |
| GET | `/midway/inspection-appointments/{id}` | Read one appointment | All roles |
| GET | `/midway/inspection-appointments` | List/filter appointments | All roles |
| POST | `/midway/inspection-appointments/{id}/complete` | Assigned inspector records PASS/FAIL; a passed `RIDE_AUDIT` resets the cycle counter and re-licenses | StateInspector |
| POST | `/midway/inspection-appointments/{id}/cancel` | Fair manager cancels a `SCHEDULED` appointment (frees inspector capacity) | FairManager |
| GET | `/midway/permits/{id}` | Read one permit (estimated vs final fee fields) | All roles |
| GET | `/midway/permits` | List/filter permits | All roles |
| POST | `/midway/permits/{id}/approve` | Approve a `PENDING` permit with segregation of duties and OCC on the fair version; computes the final fee and licenses verified rides | StateInspector |
| POST | `/midway/permits/{id}/deny` | Deny a `PENDING` permit; the fair loops back to `SETUP` | StateInspector |
| POST | `/midway/staff` | Hire a staff member into a fair (StateProgramAdmin seeds the first `SUPERVISOR`; FairManager hires the rest) | StateProgramAdmin, FairManager |
| GET | `/midway/staff/{id}` | Read one staff member | All roles |
| GET | `/midway/staff` | List/filter staff | All roles |
| POST | `/midway/staff/{id}/release` | Release staff; compensates by cancelling their future `SCHEDULED`/`CONFIRMED` shifts | FairManager |
| POST | `/midway/operator-certifications` | Issue a ride-class certification to an `OPERATOR` staff member | StateProgramAdmin |
| GET | `/midway/operator-certifications/{id}` | Read one certification | All roles |
| GET | `/midway/operator-certifications` | List/filter certifications | All roles |
| POST | `/midway/operator-certifications/{id}/revoke` | Revoke a certification | StateProgramAdmin, StateInspector |
| POST | `/midway/operating-days` | Schedule an operating day (requires fair `PERMITTED`) | FairManager |
| GET | `/midway/operating-days/{id}` | Read one operating day (settlement fields) | All roles |
| GET | `/midway/operating-days` | List/filter operating days | All roles |
| POST | `/midway/operating-days/{id}/begin-checklists` | `SCHEDULED` → `CHECKLIST_PHASE` on the day's date; resets minor-incident counters | FairManager |
| POST | `/midway/operating-days/{id}/open-gates` | `CHECKLIST_PHASE` → `OPEN`; compound gate: every licensed verified ride needs a `COUNTERSIGNED` checklist | FairManager |
| POST | `/midway/operating-days/{id}/resume-day` | `WEATHER_HOLD` → `OPEN` when the latest wind reading is at or below 39 mph | FairManager |
| POST | `/midway/operating-days/{id}/close-gates` | `OPEN`/`WEATHER_HOLD` → `CLOSED`; closes rides, expires queued redemptions and active credits, computes projected settlement | FairManager |
| POST | `/midway/operating-days/{id}/reconcile` | `CLOSED` → `RECONCILED`; computes recognized revenue and breakage | FairManager |
| POST | `/midway/daily-checklists` | Operator opens the pre-opening checklist for a ride/day (unique per ride and day) | RideOperator |
| GET | `/midway/daily-checklists/{id}` | Read one checklist | All roles |
| GET | `/midway/daily-checklists` | List/filter checklists | All roles |
| POST | `/midway/daily-checklists/{id}/submit` | Performer submits completed items (`DRAFT` → `SUBMITTED`; all items must pass) | RideOperator |
| POST | `/midway/daily-checklists/{id}/countersign` | Supervisor countersigns with OCC on the checklist version; segregation of duties vs performer; `SUBMITTED` → `COUNTERSIGNED` | FairManager |
| POST | `/midway/daily-checklists/{id}/reject` | Supervisor rejects a submission back to `DRAFT` (revision loop) | FairManager |
| POST | `/midway/ride-cycles` | Open a `LOADING` cycle for a ride/day (one active cycle per ride; operator certified for the class) | RideOperator |
| GET | `/midway/ride-cycles/{id}` | Read one cycle | All roles |
| GET | `/midway/ride-cycles` | List/filter cycles | All roles |
| POST | `/midway/ride-cycles/{id}/load` | Board `QUEUED` redemptions first-in-first-out by `queue_position` up to capacity; insufficient-credit entries void and skip | RideOperator |
| POST | `/midway/ride-cycles/{id}/dispatch` | `LOADING` → `RUNNING`; requires at least one rider and the ride still `OPEN` | RideOperator |
| POST | `/midway/ride-cycles/{id}/complete` | `RUNNING` → `COMPLETED`; increments the cycle counter and may trigger the suspension cascade at the manufacturer interval | RideOperator |
| POST | `/midway/ride-cycles/{id}/abort` | `LOADING`/`RUNNING` → `ABORTED`; refunds all boarded credits and zeroes the rider count | RideOperator |
| POST | `/midway/ride-redemptions` | Present a wristband at a ride: creates a `QUEUED` redemption after height, credit, and state gates | RideOperator |
| GET | `/midway/ride-redemptions/{id}` | Read one redemption | All roles |
| GET | `/midway/ride-redemptions` | List/filter redemptions | All roles |
| POST | `/midway/ride-redemptions/{id}/void` | Void a `QUEUED` redemption, or a `REDEEMED` one whose cycle is still `LOADING` (credit refund) | RideOperator, TicketClerk |
| POST | `/midway/ticket-products` | Configure a sellable product | FairManager |
| GET | `/midway/ticket-products/{id}` | Read one product | All roles |
| GET | `/midway/ticket-products` | List/filter products | All roles |
| POST | `/midway/ticket-products/{id}/deactivate` | Take a product off sale | FairManager |
| POST | `/midway/ticket-sales` | Sell one guest instrument (ticket, credit bundle, or wristband) with tiered pricing and service fee; gates on day capacity | TicketClerk |
| GET | `/midway/ticket-sales/{id}` | Read one sale (credit counters and computed price fields) | All roles |
| GET | `/midway/ticket-sales` | List/filter sales | All roles |
| POST | `/midway/ticket-sales/{id}/void` | Same-day void while gates are `OPEN` and no boarded redemptions exist | TicketClerk |
| POST | `/midway/weather-observations` | Record a wind reading; triggers per-ride holds and the fair-wide closure sweep (append-only) | FairManager, RideOperator |
| GET | `/midway/weather-observations/{id}` | Read one observation | All roles |
| GET | `/midway/weather-observations` | List observations | All roles |
| POST | `/midway/incident-reports` | File an incident; severity drives hold/suspend/revoke cascades and the three-minor-per-day threshold | FairManager, RideOperator |
| GET | `/midway/incident-reports/{id}` | Read one incident | All roles |
| GET | `/midway/incident-reports` | List/filter incidents | All roles |
| POST | `/midway/incident-reports/{id}/clear` | Inspector clears a `FILED` incident; the ride leaves `INCIDENT_HOLD` when no open incident remains | StateInspector |
| POST | `/midway/incident-reports/{id}/order-shutdown` | Inspector orders a shutdown: license `REVOKED`, ride closed, queued redemptions voided | StateInspector |
| POST | `/midway/crew-shifts` | Schedule a crew shift with OCC on the staff version; half-open overlap and season-window checks | FairManager |
| GET | `/midway/crew-shifts/{id}` | Read one crew shift | All roles |
| GET | `/midway/crew-shifts` | List/filter crew shifts | All roles |
| POST | `/midway/crew-shifts/{id}/confirm` | Crew member confirms their own shift | CrewMember |
| POST | `/midway/crew-shifts/{id}/complete` | Mark a confirmed shift completed | FairManager |
| POST | `/midway/crew-shifts/{id}/no-show` | Mark a scheduled/confirmed shift as no-show | FairManager |
| POST | `/midway/crew-shifts/{id}/cancel` | Cancel a scheduled/confirmed shift | FairManager |
| POST | `/midway/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC); startup default is exactly `2026-08-01T00:00:00Z` | StateProgramAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are defined where each rule lives in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FAIR_INVALID_STATE` | 409 |
| `ERR_RIDE_INVALID_STATE` | 409 |
| `ERR_PERMIT_INVALID_STATE` | 409 |
| `ERR_INVALID_DAY_POSTURE` | 409 |
| `ERR_DAY_NOT_TODAY` | 422 |
| `ERR_RIDE_NOT_OPEN` | 409 |
| `ERR_RIDE_NOT_LICENSED` | 409 |
| `ERR_CYCLE_INVALID_STATE` | 409 |
| `ERR_CYCLE_IN_PROGRESS` | 409 |
| `ERR_CYCLE_EMPTY` | 422 |
| `ERR_CHECKLIST_INVALID_STATE` | 409 |
| `ERR_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_CHECKLIST_COUNTERSIGNER_CONFLICT` | 422 |
| `ERR_DUPLICATE_CHECKLIST` | 409 |
| `ERR_HEIGHT_RESTRICTION` | 422 |
| `ERR_INSUFFICIENT_CREDITS` | 422 |
| `ERR_DAY_AT_CAPACITY` | 422 |
| `ERR_CAPACITY_ABOVE_MIDWAY` | 422 |
| `ERR_PRODUCT_INACTIVE` | 422 |
| `ERR_SALE_NOT_ACTIVE` | 409 |
| `ERR_SALE_HAS_REDEMPTIONS` | 422 |
| `ERR_WIND_ABOVE_LIMIT` | 422 |
| `ERR_CERTIFICATION_MISSING` | 422 |
| `ERR_ANNUAL_CERT_EXPIRED` | 422 |
| `ERR_INSPECTOR_UNAVAILABLE` | 422 |
| `ERR_INSPECTOR_LICENSE_EXISTS` | 409 |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 |
| `ERR_APPOINTMENT_NOT_DUE` | 422 |
| `ERR_APPOINTMENT_WINDOW_INVALID` | 422 |
| `ERR_PERMIT_APPROVER_CONFLICT` | 422 |
| `ERR_INSPECTION_REQUIRED` | 422 |
| `ERR_NO_VERIFIED_RIDES` | 422 |
| `ERR_STAFF_SHIFT_OVERLAP` | 409 |
| `ERR_SHIFT_OUT_OF_SEASON` | 422 |
| `ERR_SHIFT_INVALID_STATE` | 409 |
| `ERR_STAFF_INVALID_STATE` | 409 |
| `ERR_CERT_INVALID_STATE` | 409 |
| `ERR_INCIDENT_INVALID_STATE` | 409 |
| `ERR_INCIDENTS_OPEN` | 422 |
| `ERR_NO_COVERING_SHIFT` | 422 |
| `ERR_DAYS_STILL_ACTIVE` | 422 |
| `ERR_RIDES_NOT_DISMANTLED` | 422 |
| `ERR_RIDES_NOT_CLEARED` | 422 |
| `ERR_REDEMPTION_NOT_VOIDABLE` | 409 |
| `ERR_CROSS_FAIR_REFERENCE` | 422 |
| `ERR_DUPLICATE_OPERATING_DAY` | 409 |
| `ERR_STALE_STAFF_VERSION` | 412 |
| `ERR_STALE_FAIR_VERSION` | 412 |
| `ERR_STALE_CHECKLIST_VERSION` | 412 |
