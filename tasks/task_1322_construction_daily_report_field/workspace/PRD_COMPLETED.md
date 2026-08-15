# Construction Daily Reports API — Product Requirements Document

## 1. Introduction

The daily report is the jobsite's system of record: when a claim, dispute, or OSHA inquiry arrives months after the fact, the contractor's defense rests on what the superintendent wrote down that day. This document specifies the Construction Daily Reports API, a service that lets a general contractor capture that record with the rigor claims counsel expects — manpower and equipment counts by work area, weather observations and delay windows, safety observations and incidents, material deliveries with inspection outcomes, photo and video documentation tied to a location, time-and-material tickets with dual signatures, installed quantities for progress measurement, and controlled distribution of the finished report with a retention clock for claims.

Two design commitments shape everything that follows. First, the report is a compliance artifact, not a scratchpad: once a report leaves the superintendent's hands its content is sealed, every review action is attributed to a named operator, and paired duties — submitting versus approving, creating versus signing, creating versus closing — are deliberately segregated across roles. Second, the numbers on the report are derived, not typed: manpower splits, weather-lost-day classifications, ticket pricing, quantity rollups, and project progress percentages are all computed by the server under fixed rounding and evaluation-order rules, so two honest implementations must produce identical figures from identical inputs.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once authenticated, each operation is restricted to specific roles; an authenticated operator attempting an action outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system declares exactly six roles:

- `SystemAdmin` — the GC platform administrator: project setup, work areas, delivery zones, budget lines, the logical clock, report locking, and distribution dispatch.
- `Superintendent` — the jobsite superintendent, who owns daily report content: reports, crew, equipment, weather, delay, media, delivery, quantity, and time-and-material entry.
- `ProjectManager` — the GC project manager: report review and approval, delay classification and finalization, T&M approval and rejection, and distribution setup.
- `SafetyOfficer` — the safety officer: safety observations, incidents, and OSHA notification.
- `ContractorRep` — the subcontractor representative, who applies the contractor-side T&M signature.
- `OwnerRep` — the owner representative: the owner-side T&M signature, delay disputes, and distribution acknowledgement.

For all six roles — `SystemAdmin`, `Superintendent`, `ProjectManager`, `SafetyOfficer`, `ContractorRep`, and `OwnerRep` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares it to any resource's `id`. It does, however, record the identifier where accountability matters — as `submitted_by_user_id` on a submitted report, as `created_by_user_id` on safety observations, incidents, and T&M tickets, and as `contractor_signed_by` and `owner_signed_by` on signed tickets — and the segregation-of-duties rules compare these recorded identifiers against the caller's `X-User-ID`.

Read access is broad: every role may call every retrieval and listing endpoint. Write access is narrow and is enumerated per endpoint in §4.

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
- This serialization is uniform: every timestamp the server emits in a response body — the audit fields of §2.4, clock-stamped fields such as `submitted_at`, `osha_notified_at`, `sent_at`, `acknowledged_at`, and an escalation-stamped `occurred_at`, computed instants such as `osha_notification_deadline` and `retention_release_date`, the clock endpoint's `current_utc`, and client-supplied instants echoed back on a resource — is an ISO 8601 UTC string with exactly three fractional digits (for example, `2026-08-01T00:00:00.000Z`).
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order — the earliest-created record first.

Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`. A `limit` outside the 1–100 range, a non-numeric or negative `limit` or `offset`, an unrecognized enum filter value, or a malformed date filter value is rejected with `ERR_INVALID_REQUEST`.

### 2.4. Resource Identity and Audit Fields

Every primary resource carries a standard set of system-managed properties:

- `id` — a server-minted UUID, with no type prefix; clients never supply it.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — a system-managed integer that starts at 1 on creation (with `updated_at` equal to `created_at`) and increments by one with every modification to the resource, underpinning optimistic concurrency control.

One resource is deliberately different. A weather observation is an immutable, append-only log entry: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it, because a weather observation is never edited, voided, or transitioned after it is recorded.

### 2.5. The Logical Clock

All time-sensitive behavior in the system reads a single logical clock, never the wall clock. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it advances only when explicitly set. A `SystemAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; the clock never falls back to wall-clock time on its own.

The logical clock stamps `submitted_at`, `osha_notified_at`, `sent_at`, and `acknowledged_at` when the corresponding actions occur, supplies the "now" against which report dates and incident occurrence instants are judged, and drives the lateness flag on open incidents: setting the clock recomputes `notification_overdue` for every incident that is still open.

### 2.6. Content Posture: The Editable-Versus-Sealed Gate

A daily report's `content_posture` is computed from its status: it is `EDITABLE` while the report is in `DRAFT` or `REVISION_REQUESTED`, and `SEALED` in every other status. Content posture — not the raw status — is what gates child mutations. While a report is `SEALED`, the server rejects, with `ERR_REPORT_NOT_EDITABLE` (HTTP 409), every one of the following: creating crew entries, equipment entries, weather observations, delay events, safety observations, media attachments, material deliveries, quantity entries, and T&M tickets; voiding a crew, equipment, or quantity entry; purging a media attachment; inspecting a delivery or resolving its recount; editing the report header; replacing a T&M ticket's lines; and submitting a T&M ticket for signature. The same gate guards the ticket revision and void cycles described in §3.7.

There is exactly one carve-out, and it exists because incidents cannot wait for paperwork: incident creation, and the escalation of a safety observation into an incident, are allowed on any report that is not yet `LOCKED`, even when the report is `SEALED`. Against a `LOCKED` report, both are rejected with `ERR_INCIDENT_ON_LOCKED_REPORT` (HTTP 409).

A daily report behaves as an aggregate with respect to versioning. Almost every child-entry write or transition on a report — crew, equipment, weather, delay, safety, incident, media, delivery, and quantity activity, distribution sends, and the report's own lifecycle transitions — advances the parent report's `version` by one and refreshes its `updated_at`. The exceptions are T&M ticket line replacement on a `DRAFT` ticket, signature capture, approval, rejection, and revision, voiding a ticket from a post-`DRAFT` state, and distribution-record creation, deletion, and acknowledgement, none of which touch the report's `version`.

### 2.7. Optimistic Concurrency on Report and Ticket Writes

Three write operations carry an optimistic-concurrency guard, and no other endpoint accepts a version field.

Editing a daily report's header requires the request to carry `expected_report_version`, holding the report `version` the client last observed. If that value does not equal the report's current `version` — because any child-entry write or transition has legitimately advanced the aggregate version in between — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), and the editor must refresh its view before re-applying the change.

Recording a quantity entry against a report likewise requires `expected_report_version` matching the report's current `version`. The create can legitimately supersede — that is, void — a prior active entry for the same report, work item, and work area, so a writer working from a stale snapshot must not silently void entries it never saw; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Replacing the lines of a `DRAFT` T&M ticket requires `expected_ticket_version` matching the ticket's own current `version`. A prior edit has already repriced the ticket, so a stale writer's total and ceiling assumptions no longer hold; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Numbers, Rounding, and Money

Rounding discipline is uniform and fixed. Every rounding the server performs uses the round-half-up method. Manpower totals, delay lost-hours, weather-lost-day fractions, and project progress percentages are rounded half-up to two decimal places. Installed quantities are rounded half-up to three decimal places per entry at write time, and rollups sum the stored rounded values exactly, never re-rounding a sum.

Money is handled in integer cents throughout: rates, unit costs, ticket ceilings, and every computed cost field are integer cents. On T&M tickets, each line's cost is rounded half-up to integer cents before any summation, and the markup computation rounds half-up at each of its rounding steps; sums over already-rounded line values are then exact integer arithmetic.

### 2.9. The Validation Order

When a request violates several rules at once, the server does not choose arbitrarily which failure to report: checks execute in a fixed order, and the first failing check produces the error response. The order is as follows.

1. **Header context.** `X-User-ID` and `X-User-Role` must both be present and the role must be one of the six declared roles, on every endpoint; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization.** The role must be permitted on the endpoint per the access matrix; otherwise `ERR_FORBIDDEN`.
3. **Path existence.** Identifiers in the URL are validated left to right; the first identifier that does not resolve yields the corresponding 404 error (§2.10).
4. **Request shape.** Required fields must be present, types must match, enum members must be valid, and numeric ranges must be honored — `worker_count` at least 1, `hours_per_worker` between 0 and 24 inclusive, `delivered_qty` strictly greater than zero, `quantity_installed` strictly greater than zero, `budgeted_quantity` strictly greater than zero, `unit_cost_cents` non-negative, `buffer_minutes` non-negative, `injured_count` and `days_away` non-negative, `scheduled_shift_hours` greater than zero and at most 24; violations yield `ERR_INVALID_REQUEST`.
5. **Body references.** Foreign keys carried in the body — `report_id`, `work_area_id`, `work_item_id`, `delivery_zone_id`, `media_attachment_id`, `linked_incident_id`, `linked_delivery_id`, `safety_observation_id` — must resolve to existing rows; an unresolvable reference yields that resource's 404 error.
6. **State preconditions.** First, the target resource's own state machine must permit the requested transition from its current state, else the resource's invalid-transition error. Then the parent-report gates: the content-posture gate (`ERR_REPORT_NOT_EDITABLE`), or — for incident creation and observation escalation — the locked-report gate (`ERR_INCIDENT_ON_LOCKED_REPORT`). Then the optimistic-concurrency agreement check (`ERR_STALE_VERSION`).
7. **Safety rules.** High-risk observations without media (`ERR_HIGH_RISK_OBSERVATION_REQUIRES_MEDIA`), thin incident narratives (`ERR_INCIDENT_NARRATIVE_REQUIRED`), the linked-media and OSHA-notification requirements on a recordable close (`ERR_INCIDENT_MEDIA_REQUIRED`, `ERR_OSHA_NOTIFICATION_REQUIRED`), outcome-versus-recordability agreement (`ERR_INCIDENT_RECORDABLE_MISMATCH`), and OSHA notification applicability (`ERR_OSHA_NOT_APPLICABLE`).
8. **Business constraints.** Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) is evaluated first within this layer, then signature order (`ERR_SIGNATURE_ORDER`), then uniqueness (`ERR_DUPLICATE_CONTRACT_NUMBER`, `ERR_DUPLICATE_WORK_AREA_CODE`, `ERR_DUPLICATE_ZONE_CODE`, `ERR_DUPLICATE_COST_CODE`, `ERR_DUPLICATE_REPORT_DATE`, `ERR_DUPLICATE_RECIPIENT`), then equipment capacity (`ERR_EQUIPMENT_CAPACITY_EXCEEDED`), media linkage and GPS pairing (`ERR_MEDIA_LINK_CONSTRAINT`, `ERR_GPS_INCOMPLETE_PAIR`), idempotency conflicts (`ERR_IDEMPOTENCY_CONFLICT`), ticket non-emptiness (`ERR_TICKET_EMPTY`), inspection quantity bounds (`ERR_INSPECTION_QTY_OVERFLOW`), and purge linkage (`ERR_MEDIA_LINKED_TO_INCIDENT`).
9. **Temporal rules.** Future report dates (`ERR_REPORT_DATE_FUTURE`), out-of-day weather and media timestamps (`ERR_WEATHER_OUTSIDE_REPORT_DATE`, `ERR_MEDIA_CAPTURED_OUTSIDE_REPORT_DATE`), incidents dated in the future (`ERR_INCIDENT_OCCURRED_IN_FUTURE`), malformed windows (`ERR_DELAY_WINDOW_INVALID`, `ERR_INVALID_WINDOW`), compensable delay overlap (`ERR_DELAY_OVERLAP_COMPENSABLE`), and delivery-window collisions (`ERR_DELIVERY_WINDOW_OVERLAP`).
10. **Referential gates.** Closed work areas and delivery zones (`ERR_WORK_AREA_CLOSED`, `ERR_DELIVERY_ZONE_CLOSED`), cross-report media references (`ERR_MEDIA_REPORT_MISMATCH`), the report-submit content gates (`ERR_WEATHER_MISSING`, `ERR_NO_WORK_RECORDED`, `ERR_WORK_ENTRIES_CONFLICT`, `ERR_DELIVERY_NOT_INSPECTED`, `ERR_DELAY_EVENT_UNCLASSIFIED`), the distribution gates (`ERR_REPORT_NOT_APPROVED`, `ERR_DISTRIBUTION_HOLD`, `ERR_DISTRIBUTION_ALREADY_SENT`), the delay report-state gates (`ERR_DELAY_LOCKED_REPORT`, `ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT`), the project/report activity gates (`ERR_PROJECT_NOT_ACTIVE`, `ERR_PROJECT_HAS_OPEN_REPORTS`), and the T&M report-state gate (`ERR_TICKET_REPORT_NOT_SUBMITTED`).
11. **The fiscal gate.** Last of all, the not-to-exceed ceiling check on T&M approval (`ERR_TM_CEILING_EXCEEDED`).

### 2.10. Existence Checks and the Not-Found Vocabulary

Requests that carry resource identifiers — in the path or in the body — are validated for existence in a strict left-to-right order, and the first identifier that does not resolve determines the error. A missing project yields `ERR_PROJECT_NOT_FOUND`; a missing daily report `ERR_REPORT_NOT_FOUND`; a missing work area `ERR_WORK_AREA_NOT_FOUND`; a missing budget line `ERR_WORK_ITEM_NOT_FOUND`; a missing delivery zone `ERR_DELIVERY_ZONE_NOT_FOUND`; a missing delivery `ERR_DELIVERY_NOT_FOUND`; a missing delay event `ERR_DELAY_EVENT_NOT_FOUND`; a missing safety observation `ERR_OBSERVATION_NOT_FOUND`; a missing incident `ERR_INCIDENT_NOT_FOUND`; a missing media attachment `ERR_MEDIA_NOT_FOUND`; a missing T&M ticket `ERR_TICKET_NOT_FOUND`; and a missing distribution record `ERR_DISTRIBUTION_RECORD_NOT_FOUND`. Crew entries, equipment entries, quantity entries, and weather observations share the generic `ERR_NOT_FOUND`. All of these are HTTP 404.

### 2.11. Idempotent Capture for Field Events

Field conditions are chaotic, and a superintendent retrying a submission on a flaky connection must not create duplicates. Three creation flows accept an optional `idempotency_key`: capturing an incident, creating a T&M ticket, and attaching media. When a key is supplied, the server remembers it together with the request body, scoped to the endpoint path plus the caller's `X-User-ID`. Replaying the same key with an identical body returns the originally created resource, with the same 201 Created status as the original call, rather than creating a second one; reusing the same key with a different body is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Standing Up the Project: Areas, Zones, and Budget Lines

Before any field reporting begins, a `SystemAdmin` stands up the project shell. Creating a project requires a `name` and a `contract_number`; the contract number is globally unique, and a duplicate is rejected with `ERR_DUPLICATE_CONTRACT_NUMBER`. Two scheduling defaults anchor every delay computation on the project's reports: `scheduled_shift_start`, an HH:MM 24-hour clock time defaulting to `07:00`, and `scheduled_shift_hours`, the scheduled workday length defaulting to 8 and required to be greater than zero and at most 24. The `retention_days` parameter, defaulting to 2555 days, sets how long distributed reports are retained for claims.

A project is born `MOBILIZING`. Activation by a `SystemAdmin` moves it to `ACTIVE`; suspension moves `ACTIVE` to `SUSPENDED`; resumption returns `SUSPENDED` to `ACTIVE`; and closing moves either `ACTIVE` or `SUSPENDED` to `CLOSED`, the terminal state. Each of these transitions requires the matching source state — otherwise `ERR_PROJECT_INVALID_TRANSITION` — and each increments the project's `version` by one. Closing carries a second gate: every daily report on the project must already be `LOCKED`, else the close is refused with `ERR_PROJECT_HAS_OPEN_REPORTS`. Only an `ACTIVE` project accepts submitted reports; a submit against a project in any other state fails with `ERR_PROJECT_NOT_ACTIVE`.

Within the project, the administrator then defines the geography and the budget. A work area carries a `code` that is unique within its project — duplicates fail with `ERR_DUPLICATE_WORK_AREA_CODE` — and an optional `description`. Areas open in `OPEN` status; a `SystemAdmin` may close an `OPEN` area and reopen a `CLOSED` one, with any other attempt rejected as `ERR_WORK_AREA_INVALID_TRANSITION` and each transition bumping the area's `version`. A `CLOSED` area refuses new child entries of every kind — crew, equipment, delay, safety, media, quantity, and incident records alike — with `ERR_WORK_AREA_CLOSED`. Delivery zones work the same way: a `zone_code` unique within the project (`ERR_DUPLICATE_ZONE_CODE` on collision), a `buffer_minutes` value defaulting to 30 and never negative, an `OPEN`/`CLOSED` lifecycle driven by close and reopen actions (`ERR_ZONE_INVALID_TRANSITION` when the source state is wrong, `version` incrementing each time), and a hard refusal — `ERR_DELIVERY_ZONE_CLOSED` — of any new delivery aimed at a `CLOSED` zone.

Budget lines complete the setup. Each work item records a `cost_code` unique within its project (`ERR_DUPLICATE_COST_CODE`), a `description`, a strictly positive `budgeted_quantity`, a `unit` drawn from `LF`, `SF`, `CY`, `EA`, `TON`, or `GAL`, and a non-negative `unit_cost_cents`. A fresh work item starts with `installed_to_date` at zero and `status` `NOT_STARTED`; both are computed thereafter — the item is `IN_PROGRESS` while installed quantity is greater than zero and less than the budget, and `COMPLETE` once installed quantity reaches or exceeds the budget. The project register can be listed with a `status` filter; areas, zones, and budget lines can each be listed filtered by `project_id` and `status`; and the project read exposes the two computed progress figures `percent_complete_units` and `percent_complete_cost` described in §3.8.

### 3.2. The Daily Report Header: Drafting the Day's Record

Each reporting day begins when a `Superintendent` creates the daily report for a project. The payload names the `project_id` and the `report_date` — a YYYY-MM-DD calendar date interpreted in UTC — and may optionally carry free-text `general_notes`, the actual crew start and end instants `shift_start_actual` and `shift_end_actual`, and the `no_work_performed` flag, which defaults to false. One report exists per project per date: a second report for the same project and `report_date` is rejected with `ERR_DUPLICATE_REPORT_DATE`. A new report is born in `DRAFT` status with `content_posture` `EDITABLE`, a `revision_count` of zero, and empty computed totals.

While the report remains `EDITABLE`, the superintendent may revise the header — `general_notes`, `shift_start_actual`, `shift_end_actual`, and `no_work_performed` are the editable fields; the project and date are fixed at creation. Only fields present in the request body are modified: `general_notes`, `shift_start_actual`, and `shift_end_actual` sent with an explicit null are cleared to null, while a null `no_work_performed` is ignored. This edit is one of the three OCC-guarded writes of §2.7: the request must carry `expected_report_version` equal to the report's current `version`, a stale value draws `ERR_STALE_VERSION`, and a successful edit increments the report's `version`.

The report register supports listing filtered by `project_id`, by `status`, by an inclusive date range via `report_date_from` and `report_date_to` (reports dated exactly on either bound match), and by `retention_class`. The full report read returns every computed field: the manpower totals, the weather lost-time figures, the incident-driven hold flags, and the retention fields, all of which the following subsections define.

### 3.3. Crews and Iron: Manpower and Equipment Lines

A `Superintendent` builds the day's manpower picture one crew line at a time. Each crew entry names its `report_id` and `work_area_id`, the `subcontractor` and `trade`, a `worker_count` of at least one, the `hours_per_worker` worked that day between 0 and 24 inclusive, and a free-text `work_performed` description of what the crew accomplished in that area.

The server splits each active crew line into three pay bands with exact boundaries. The line's `regular_hours` are its `worker_count` multiplied by the smaller of `hours_per_worker` and eight — the first eight hours per worker are regular time. Its `ot_hours` are `worker_count` multiplied by the smaller of (the excess of `hours_per_worker` above eight, never below zero) and four — overtime covers only the band strictly above eight hours and up to twelve. Its `dt_hours` are `worker_count` multiplied by the excess of `hours_per_worker` above twelve, never below zero — double time starts strictly above twelve. The boundaries pin exactly: a worker logging exactly eight hours accrues zero overtime, and a worker logging exactly twelve hours accrues exactly four overtime hours and zero double time. All three band figures are rounded half-up to two decimal places.

Report totals aggregate active lines only. `total_workers` sums `worker_count` over `ACTIVE` crew entries, and `manhours_regular`, `manhours_ot`, and `manhours_dt` sum the per-line band figures over `ACTIVE` rows, each rounded half-up to two decimals; `VOIDED` lines contribute nothing. Crew lines themselves cycle from `ACTIVE` to `VOIDED`: voiding requires the line to be `ACTIVE` (else `ERR_ENTRY_INVALID_TRANSITION`) and the parent report `EDITABLE` (else `ERR_REPORT_NOT_EDITABLE`), and it recomputes the report's manpower totals while advancing the report's `version`.

Equipment lines follow the same shape with a capacity twist. Each equipment entry records its `report_id`, `work_area_id`, an `equipment_type`, a `unit_count` of at least one, and non-negative `hours_used` and `hours_idle`. One physical day bounds each unit: the sum of `hours_used` and `hours_idle` must not exceed twenty-four hours per unit multiplied by `unit_count`, with equality allowed — a breach is rejected with `ERR_EQUIPMENT_CAPACITY_EXCEEDED`. Equipment entries share the crew entry lifecycle: `ACTIVE` to `VOIDED` while the report is `EDITABLE`, under the same two errors, with the report's `version` advancing on both creation and void. Both registers can be listed filtered by `report_id`, `work_area_id`, and `status`.

### 3.4. Weather and Delay: Accounting for Lost Time

Weather is captured as an append-only log. A `Superintendent` appends a weather observation to an `EDITABLE` report, supplying `report_id`, the `observed_at` instant, a `condition` of `CLEAR`, `CLOUDY`, `RAIN`, `SNOW`, `WIND`, `EXTREME_HEAT`, or `EXTREME_COLD`, and a `work_impact` of `NONE`, `PARTIAL`, or `STOPPAGE`; `temperature_f`, non-negative `precipitation_in`, and non-negative `wind_mph` are optional. The observation must belong to the day it documents: `observed_at` has to fall within the `report_date` calendar day, from midnight UTC inclusive to the following midnight exclusive, else the record is rejected with `ERR_WEATHER_OUTSIDE_REPORT_DATE`. Observations are immutable once written — there is no edit and no void — and each append advances the parent report's `version`. The log can be listed filtered by `report_id`. Two downstream rules hang off this log: a report cannot be submitted without at least one observation (§3.9), and a `STOPPAGE` observation arms the equipment standby multiplier on T&M tickets (§3.7).

Delays are recorded as half-open windows. A delay event names its `report_id` and `work_area_id`, a `start_at` and an `end_at` that must be strictly after the start — otherwise `ERR_DELAY_WINDOW_INVALID` — and a `cause` of `WEATHER`, `OWNER`, `MATERIAL`, `LABOR`, `EQUIPMENT`, or `OTHER`. A new event sits in `RECORDED` status with its `classification` null until a `ProjectManager` classifies it.

Classification moves the event from `RECORDED` to `CLASSIFIED`, writes one of the four classification values — `EXCUSABLE_COMPENSABLE`, `EXCUSABLE_NON_COMPENSABLE`, `NON_EXCUSABLE`, or `CONCURRENT` — and computes the event's `lost_hours`. That computation measures the overlap between the delay window and the report's scheduled shift window. The shift window opens at the actual shift start when `shift_start_actual` is recorded on the report, and otherwise at the project's `scheduled_shift_start` on the `report_date` in UTC; it runs for the project's `scheduled_shift_hours` as a half-open interval that includes its opening instant and excludes its closing one. The delay window is likewise half-open, including `start_at` and excluding `end_at`. The lost hours are the length of the intersection of the two windows, in hours, rounded half-up to two decimal places. A delay lying entirely outside the shift yields exactly zero, and a delay that merely touches the shift boundary contributes zero as well. Classification is forbidden once the parent report is `APPROVED` or `LOCKED` — the attempt fails with `ERR_DELAY_LOCKED_REPORT` — and one overlap prohibition protects the compensable classification: an event may not be classified `EXCUSABLE_COMPENSABLE` when another event on the same `work_area_id`, itself classified `EXCUSABLE_COMPENSABLE` and sitting in `CLASSIFIED` or `FINAL` status, has a window overlapping this one. Because both windows are half-open, adjacency is not overlap — one window ending exactly where the other begins is permitted. A violating classification is rejected with `ERR_DELAY_OVERLAP_COMPENSABLE`.

The dispute cycle runs through the owner's representative. An `OwnerRep` may dispute a `CLASSIFIED` event regardless of the parent report's status, moving it to `DISPUTED` and capturing a `reason` that is stored on the event as `dispute_reason`; while disputed, the event drops out of the report's weather totals. A `ProjectManager` may then re-classify a `DISPUTED` event back to `CLASSIFIED`, overwriting its classification under the same overlap prohibition, or finalize a `CLASSIFIED` event to the terminal `FINAL` status. Finalization requires the parent report to have been submitted — the report must be in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED`, else `ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT`. Any classification attempted against a status other than `RECORDED` or `DISPUTED`, and any dispute or finalization from a mismatched status, fails with `ERR_DELAY_INVALID_TRANSITION`. Classifications, disputes, and finalizations each advance the parent report's `version`.

From the classified events the server derives the report's weather lost-time figures, which recompute on every classification, dispute, and re-classification. `weather_lost_hours` sums `lost_hours` across the report's delay events whose `cause` is `WEATHER`, whose status is `CLASSIFIED` or `FINAL`, and whose `classification` is one of the two excusable values; `RECORDED` and `DISPUTED` events never contribute. Two published variants share that single input set. The calendar-day variant, `weather_lost_day_calendar`, is a boolean that is true exactly when the lost hours reach at least half of the project's `scheduled_shift_hours` — at exactly half the shift, the day counts as lost. The prorated variant, `weather_lost_day_fraction`, is the lost hours divided by `scheduled_shift_hours`, capped at one, and rounded half-up to two decimal places. The delay register lists events filtered by `report_id`, `work_area_id`, and `status`.

### 3.5. Safety: Observations, Incidents, and OSHA Duties

A `SafetyOfficer` records a safety observation on an `EDITABLE` report, providing `report_id`, `work_area_id`, a `description`, and a `risk_level` of `LOW`, `MEDIUM`, or `HIGH`; `corrective_action` text and a `due_date` in YYYY-MM-DD form are optional. The server records the creator's `X-User-ID` as `created_by_user_id` and opens the observation in `OPEN` status. A `HIGH`-risk observation must be evidenced: it is rejected without a `media_attachment_id`, failing with `ERR_HIGH_RISK_OBSERVATION_REQUIRES_MEDIA`, and the referenced media must be `ACTIVE` and attached to the same report, else `ERR_MEDIA_REPORT_MISMATCH`.

The observation lifecycle is a small loop with a segregated exit. Mitigation moves `OPEN` to `MITIGATED`; verification moves `MITIGATED` to the terminal `VERIFIED_CLOSED`, but only when performed by a different operator than the one who created the observation — the creator's verify-close attempt fails with `ERR_SEGREGATION_OF_DUTIES`. A mitigated finding can regress: reopening moves `MITIGATED` back to `OPEN`. Any of these actions from the wrong status fails with `ERR_OBSERVATION_INVALID_TRANSITION`, and each advances the parent report's `version`.

When an observation is more than a finding, escalation moves it from `OPEN` to the terminal `ESCALATED` and simultaneously creates a linked incident. Escalation obeys the incident carve-out of §2.6: it is permitted on any report that is not `LOCKED`, sealed or not, and fails with `ERR_INCIDENT_ON_LOCKED_REPORT` against a locked one. The created incident references the observation through `safety_observation_id`, stamps `occurred_at` with the logical clock, starts at severity `MEDICAL_TREATMENT` in `REPORTED` status with `injured_count` and `days_away` at zero, and takes its initial `narrative` verbatim from the observation's description — the fifty-character narrative minimum of direct capture is not applied on this path, and the work-area-open check of §3.1 is not re-applied either; the observation's own `incident_id` is set to point at it. The new open incident immediately recomputes the report's posture flags: `has_open_incident` flips to true, `distribution_hold` follows it to true, and every `PENDING` distribution record on the report flips to `BLOCKED` — the distribution freeze described in §3.9.

Incidents may also be captured directly by a `SafetyOfficer`, and the same carve-out applies: incident creation is allowed on any report that is not `LOCKED`, even a `SEALED` one. The payload carries `report_id`, `work_area_id`, the `occurred_at` instant — which must not lie in the future of the logical clock, else `ERR_INCIDENT_OCCURRED_IN_FUTURE` — a `severity` of `FIRST_AID`, `NEAR_MISS`, `PROPERTY_DAMAGE`, `MEDICAL_TREATMENT`, `LOST_TIME`, or `FATALITY`, and a `narrative`. `injured_count` and `days_away` default to zero and must be non-negative, `safety_observation_id` is optional, and the idempotency mechanism of §2.11 is available. When severity is `MEDICAL_TREATMENT`, `LOST_TIME`, or `FATALITY`, the narrative must run to at least fifty characters — thinner accounts are rejected with `ERR_INCIDENT_NARRATIVE_REQUIRED`. Those same three severities are exactly the recordable ones: the computed `recordable` flag is true for them and false for the rest. Incident creation bumps the parent report's `version` and fires the same hold cascade as escalation; when the new incident is recordable, the report's `retention_class` also flips to `CLAIMS_HOLD`, a sticky classification that survives the incident's later closure.

Two federal clocks start at `occurred_at`. A `FATALITY` incident's `osha_notification_deadline` falls eight hours after occurrence; a `LOST_TIME` incident's falls twenty-four hours after; every other severity carries no deadline at all. The computed `notification_overdue` flag is true only when the incident is recordable, a deadline exists, `osha_notified_at` is still null, and the logical clock reads strictly later than the deadline — at the deadline instant exactly, the incident is not yet overdue. The flag recomputes whenever the logical clock is set.

The incident lifecycle runs `REPORTED` to `UNDER_INVESTIGATION` when a `SafetyOfficer` begins the investigation, and from either of those states to `OSHA_NOTIFIED` when notification occurs — a transition reserved for recordable incidents, so notifying on a non-recordable incident fails with `ERR_OSHA_NOT_APPLICABLE`, while a successful notification stamps `osha_notified_at` from the logical clock. Closure takes an explicit `outcome` of `RECORDABLE` or `NOT_RECORDABLE`, and the outcome must agree with the computed `recordable` flag: a `RECORDABLE` close of a non-recordable incident, or the reverse, fails with `ERR_INCIDENT_RECORDABLE_MISMATCH`. A `NOT_RECORDABLE` close is permitted from `REPORTED` or `UNDER_INVESTIGATION`. A `RECORDABLE` close is permitted from `REPORTED`, `UNDER_INVESTIGATION`, or `OSHA_NOTIFIED`, and carries two further duties: if a notification deadline exists, notification must already have occurred (else `ERR_OSHA_NOTIFICATION_REQUIRED`), and at least one `ACTIVE` media attachment must be linked to the incident (else `ERR_INCIDENT_MEDIA_REQUIRED`). In every close, the operator performing it must differ from the incident's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and any close or transition attempted from a mismatched status fails with `ERR_INCIDENT_INVALID_TRANSITION`.

Closing the last open incident unwinds the freeze. The report's `has_open_incident` recomputes — true while any linked incident sits outside the two closed states `CLOSED_RECORDABLE` and `CLOSED_NOT_RECORDABLE` — and when this was the final open incident it flips to false, `distribution_hold` follows it to false, and every `BLOCKED` distribution record on the report flips back to `PENDING`. A recordable close adds one more term: the report's `retention_class` stays `CLAIMS_HOLD` forever, and its `retention_release_date` remains null even after the hold clears (§3.9). Incident transitions advance the parent report's `version`. The incident register lists records filtered by `report_id`, `work_area_id`, `status`, `recordable` — given as the string `true` or `false` — and `safety_observation_id`; the observation register filters by `report_id`, `work_area_id`, `status`, `risk_level`, `incident_id`, and `media_attachment_id`.

### 3.6. Visual and Material Evidence: Media Attachments and Deliveries

Photo and video documentation is tied to a place and a day. Either a `Superintendent` or a `SafetyOfficer` attaches media to an `EDITABLE` report, supplying `report_id`, the `work_area_id` the media documents, a `media_type` of `PHOTO` or `VIDEO`, the stored `file_url`, and the `captured_at` instant — which, like a weather observation, must fall within the `report_date` calendar day from midnight UTC inclusive to the following midnight exclusive, else `ERR_MEDIA_CAPTURED_OUTSIDE_REPORT_DATE`. Location coordinates come as a pair or not at all: supplying exactly one of `gps_lat` and `gps_lng` is rejected with `ERR_GPS_INCOMPLETE_PAIR`. A single attachment supports at most one evidentiary link — `linked_incident_id` or `linked_delivery_id`, never both, else `ERR_MEDIA_LINK_CONSTRAINT` — and whichever target is linked must belong to the same report as the attachment, else `ERR_MEDIA_REPORT_MISMATCH`. New attachments are `ACTIVE`, creation advances the report's `version`, and the idempotency mechanism of §2.11 applies.

Purging is the only media transition, moving `ACTIVE` to the terminal `PURGED`, and it is guarded three ways: the report must be `EDITABLE` (else `ERR_REPORT_NOT_EDITABLE`), an already-purged attachment cannot be purged again (`ERR_MEDIA_INVALID_TRANSITION`), and media linked to an incident may never be purged — the attempt fails with `ERR_MEDIA_LINKED_TO_INCIDENT`. When purged media was referenced by an `OPEN` or `MITIGATED` safety observation's `media_attachment_id`, the purge clears that reference to null as an ordinary mutation of the observation, refreshing its `updated_at` and `version`. The media register lists attachments filtered by `report_id`, `work_area_id`, `linked_incident_id`, `linked_delivery_id`, and `status`.

Material deliveries are logged against a delivery zone with a scheduled window. A `Superintendent` records `report_id`, `delivery_zone_id`, the `po_number`, a `material_description`, a strictly positive `delivered_qty`, a `unit` from the same six-value unit vocabulary as budget lines, the `scheduled_window_start` and `scheduled_window_end`, and optional `inspection_notes`. The window is a closed interval — both endpoint instants are included — and its end must be strictly after its start, else `ERR_INVALID_WINDOW`. Two deliveries in the same zone may not crowd each other, regardless of which reports the existing deliveries belong to: windows must be separated by at least the zone's `buffer_minutes` on both sides, meaning a later window must begin at least `buffer_minutes` after the earlier window's end and, symmetrically, an earlier window must end at least `buffer_minutes` before the later window's start. Two windows that merely touch, with no buffer between them, count as a collision and are rejected with `ERR_DELIVERY_WINDOW_OVERLAP`. The zone must be `OPEN` (§3.1), and a new delivery starts in `DELIVERED` status with `accepted_qty` and `rejected_qty` at zero and `pending_recount_qty` initialized to the full `delivered_qty`.

Inspection partitions the delivery, and one invariant holds at all times: accepted plus rejected plus pending recount always equals the delivered quantity. Each inspection call supplies a non-negative `accepted_qty` and `rejected_qty` whose sum must not exceed the current `pending_recount_qty` — otherwise `ERR_INSPECTION_QTY_OVERFLOW` — and may refresh `inspection_notes`. The supplied quantities add into the running accepted and rejected totals and draw down the pending remainder. When the split exactly exhausts the pending remainder, the delivery lands in the terminal `INSPECTED` status; when any remainder is left, it lands in `PARTIAL` and awaits further inspection. A recount resolution shortcut settles a `PARTIAL` delivery in one step: the superintendent supplies `recount_accepted_qty` — non-negative and not exceeding the pending remainder, under the same `ERR_INSPECTION_QTY_OVERFLOW` guard — the accepted total gains that amount, the rejected total gains whatever of the pending remainder remains, the pending remainder goes to zero, and the delivery becomes `INSPECTED`. Inspections and recount resolutions are allowed only while the parent report is `EDITABLE`, only from `DELIVERED` or `PARTIAL` status as the transition requires (else `ERR_DELIVERY_INVALID_TRANSITION`), and each advances the report's `version`. The delivery register lists records filtered by `report_id`, `delivery_zone_id`, and `status`.

### 3.7. Time-and-Material Tickets: Pricing, Signatures, and Approval

Extra work performed on a time-and-material basis is documented on a T&M ticket, which a `Superintendent` creates against an `EDITABLE` report. The ticket names its `report_id`, the `work_item_id` whose cost code the work bills against, and a `description` of the work, and it carries three line arrays plus an optional `authorized_ceiling_cents` — a not-to-exceed ceiling that, when set, must itself be strictly positive. Each labor line in `labor_lines` — which may be an empty array — records a `trade`, a `worker_count` of at least one, non-negative `regular_hours`, `ot_hours`, and `dt_hours`, and a non-negative `rate_cents`. The optional `equipment_lines` array holds lines of `equipment_type`, non-negative `hours`, non-negative `rate_cents`, and a `standby` flag. The optional `material_lines` array holds lines of `description`, a strictly positive `quantity`, and a non-negative `unit_price_cents`. Ticket creation prices the ticket immediately, starts it in `DRAFT`, advances the report's `version`, and honors the idempotency mechanism of §2.11.

Pricing follows a fixed evaluation order with no ambiguity. Every line is rounded half-up to integer cents before any summation. A labor line costs its `worker_count` multiplied by the per-worker charge — `regular_hours` at the straight `rate_cents`, `ot_hours` at one and a half times `rate_cents`, and `dt_hours` at twice `rate_cents` — rounded to integer cents, and `labor_cost_cents` is the exact sum of those line costs. An equipment line costs its `hours` multiplied by its `rate_cents`, halved when the line's `standby` flag is set and the ticket's parent report carries at least one weather observation whose `work_impact` is `STOPPAGE`; in every other case the full rate applies, and each line rounds to integer cents before summing into `equipment_cost_cents`. Materials price in four pinned steps: first `materials_subtotal_cents` is the sum, over material lines, of `quantity` multiplied by `unit_price_cents` rounded half-up to integer cents; second, the markup tier is selected from that pre-markup subtotal alone — a subtotal of one hundred thousand cents or less takes the ten percent markup, anything above takes the five percent markup, so a subtotal of exactly one hundred thousand cents stays in the low tier; third, `materials_markup_cents` is the subtotal multiplied by the tier percentage, rounded half-up to integer cents; fourth, `materials_cost_cents` is the subtotal plus the markup. The tier is never selected from the marked-up amount. The ticket's `total_cents` is then `labor_cost_cents` plus `equipment_cost_cents` plus `materials_cost_cents`.

While the ticket is `DRAFT` and its parent report `EDITABLE`, the superintendent may replace its `description`, any of the three line arrays, or `authorized_ceiling_cents` — only the fields present in the request are replaced, and an explicit null `authorized_ceiling_cents` clears the ceiling; this replacement is the third OCC-guarded write of §2.7 — the request must carry `expected_ticket_version` equal to the ticket's current `version`, a stale value draws `ERR_STALE_VERSION` — and a successful replacement reprices the ticket and increments the ticket's `version`.

The signature chain enforces both order and segregation. Submitting a `DRAFT` ticket for signature requires a priced total greater than zero — an empty ticket fails with `ERR_TICKET_EMPTY` — and moves the ticket to `PENDING_SIGNATURES`, advancing the report's `version`. Signing always names a `signer_role` of `CONTRACTOR` or `OWNER`, and the declared role must match the caller's actual role: `CONTRACTOR` signing is the `ContractorRep`'s act and `OWNER` signing the `OwnerRep`'s, with a role mismatch rejected as `ERR_FORBIDDEN`. Order is enforced: the owner signature is only effective once the contractor has signed, and an owner attempt while `contractor_signed_by` is still null fails with `ERR_SIGNATURE_ORDER`. Segregation is enforced twice over: no signer may be the ticket's `created_by_user_id`, and the owner signer must additionally differ from the contractor signer, with violations failing as `ERR_SEGREGATION_OF_DUTIES`. A successful contractor signature moves the ticket from `PENDING_SIGNATURES` to `PARTIALLY_SIGNED` and records `contractor_signed_by`; the subsequent owner signature moves `PARTIALLY_SIGNED` to `FULLY_SIGNED` and records `owner_signed_by`. Signatures are accepted only from those two states — any other status fails with `ERR_TICKET_INVALID_TRANSITION`, as does a contractor attempt when `contractor_signed_by` is already set.

Approval is the `ProjectManager`'s call, gated three ways beyond the state requirement. The ticket must be `FULLY_SIGNED`; its parent report must have left the superintendent's hands — a report still in `DRAFT` or `REVISION_REQUESTED` fails the approval with `ERR_TICKET_REPORT_NOT_SUBMITTED`; and when `authorized_ceiling_cents` is set, `total_cents` must not exceed it, with equality passing — an over-ceiling ticket fails with `ERR_TM_CEILING_EXCEEDED`. The approver must also differ from the ticket's creator, else `ERR_SEGREGATION_OF_DUTIES`. Approval moves the ticket to the terminal `APPROVED`. Rejection instead moves `FULLY_SIGNED` to `REJECTED` and captures a `reason` stored as `reject_reason`. From `REJECTED`, the superintendent may run the revision cycle back to `DRAFT` — provided the parent report is `EDITABLE` — which increments the ticket's `revision_count` and clears both `contractor_signed_by` and `owner_signed_by` to null, resetting the chain while leaving the stored `reject_reason` in place. Voiding discards a ticket entirely: permitted from `DRAFT`, `PENDING_SIGNATURES`, `PARTIALLY_SIGNED`, or `REJECTED` while the report is `EDITABLE`, landing in the terminal `VOID`; a void performed from `DRAFT` also advances the report's `version`, while voids from the later states leave the report untouched. The ticket register lists records filtered by `report_id`, `work_item_id`, and `status`.

### 3.8. Measuring Progress: Quantity Entries and Rollups

Installed quantities feed the project's progress measurement. A `Superintendent` records a quantity entry naming `report_id`, `work_item_id`, `work_area_id`, and a strictly positive `quantity_installed`. This is the second OCC-guarded write of §2.7: the request must carry `expected_report_version` equal to the report's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` — the guard exists precisely because of what creation does next.

Two things happen at write time. First, the entered quantity is rounded: the entry's `rounded_quantity` is `quantity_installed` rounded half-up to three decimal places, computed once at write time and stored. Second, the new entry supersedes any existing `ACTIVE` entry for the same report, work item, and work area triple: that prior row flips to `VOIDED` and its `supersedes_id` is set to point at the replacement row. Quantity entries can also be voided directly — `ACTIVE` to `VOIDED` while the report is `EDITABLE`, under the same `ERR_ENTRY_INVALID_TRANSITION` and `ERR_REPORT_NOT_EDITABLE` guards as the other entry types. Creation and voiding each advance the report's `version`, and the register lists entries filtered by `report_id`, `work_item_id`, `work_area_id`, `status`, and `supersedes_id`.

Rollups sum stored values and never re-round. A work item's `installed_to_date` is the exact sum of `rounded_quantity` over quantity entries that are `ACTIVE` and sit on reports in `APPROVED` or `LOCKED` status. The rounding order is pinned because the two orders diverge: two entries of 1.2344 each store 1.234 apiece and roll up to an installed total of 2.468 — summing the raw values first would have produced 2.469.

Report approval is what moves quantities into the rollup, and the cascade runs in three levels. At the first level, for each work item referenced by `ACTIVE` quantity entries on the approved report, `installed_to_date` increases by each entry's `rounded_quantity`. At the second level, every work item so touched recomputes its `status` — `NOT_STARTED` at zero, `IN_PROGRESS` above zero and below budget, `COMPLETE` at or above budget. At the third level, the project's two progress percentages recompute. The units-based variant, surfaced as `percent_complete_units`, is the unweighted mean across all of the project's work items — regardless of status — of each item's `installed_to_date` capped at its `budgeted_quantity` and divided by that budget, expressed as a percentage and rounded half-up to two decimals; a project with no work items reads zero. The cost-weighted variant, `percent_complete_cost`, divides the sum over items of `installed_to_date` multiplied by `unit_cost_cents` by the sum over items of `budgeted_quantity` multiplied by `unit_cost_cents`, expressed as a percentage and rounded half-up to two decimals; it is deliberately uncapped, so over-installation pushes it above one hundred, and it reads zero when the denominator is zero. Both variants are exposed side by side — as `units_based_pct` and `cost_weighted_pct`, alongside `project_id` and a `work_item_count` — on the project's progress summary.

Reopening an approved report runs the exact compensation: the same entries' stored `rounded_quantity` values are subtracted back out of `installed_to_date`, the affected work items recompute their status, and the project's percent fields recompute. Because rollups sum stored values, the subtraction undoes the approval exactly.

### 3.9. Review, Distribution, and Retention

Submission is the superintendent's hand-off, and it runs a full precondition sweep against the `DRAFT` report. The report must be `DRAFT` (else `ERR_REPORT_INVALID_TRANSITION`); the project must be `ACTIVE` (else `ERR_PROJECT_NOT_ACTIVE`); the `report_date` must not lie after the logical clock's current date (else `ERR_REPORT_DATE_FUTURE`); at least one weather observation must exist on the report (else `ERR_WEATHER_MISSING`); exactly one of the two labor signals must hold — either at least one `ACTIVE` crew entry, or `no_work_performed` set true — so a report with no active crew and the flag still false fails with `ERR_NO_WORK_RECORDED`, while a report asserting `no_work_performed` that still carries `ACTIVE` crew entries fails with `ERR_WORK_ENTRIES_CONFLICT`; every material delivery on the report must be `INSPECTED`, so a delivery still `DELIVERED` or `PARTIAL` blocks submission with `ERR_DELIVERY_NOT_INSPECTED`; and no delay event may remain `RECORDED`, else `ERR_DELAY_EVENT_UNCLASSIFIED`. A successful submission moves the report to `SUBMITTED`, records the caller's `X-User-ID` as `submitted_by_user_id`, stamps `submitted_at` from the logical clock, recomputes `content_posture` to `SEALED`, and advances the report's `version`.

Review belongs to the `ProjectManager`. Starting review moves `SUBMITTED` to `UNDER_REVIEW`. Approval moves `UNDER_REVIEW` to `APPROVED`, but never by the report's own submitter — an approver whose `X-User-ID` equals `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` — and approval fires the three-level quantity rollup cascade of §3.8 before recomputing the posture to `SEALED` and advancing the `version`. Requesting revision moves `UNDER_REVIEW` to `REVISION_REQUESTED`, requiring a `reason` string in the request body (validated but not stored), incrementing `revision_count` by one, and returning the posture to `EDITABLE`; the superintendent then works the report and either resubmits or uses return-to-draft to move `REVISION_REQUESTED` back to `DRAFT`. Two escape hatches round out the cycle. Recall lets the superintendent pull a `SUBMITTED` report back to `DRAFT` — but only the original submitter may recall, anyone else drawing `ERR_SEGREGATION_OF_DUTIES` — restoring the `EDITABLE` posture. Reopen lets a `ProjectManager` move an `APPROVED` report back to `UNDER_REVIEW`, likewise requiring a `reason` string that is validated but not stored, and running the exact compensating rollup of §3.8. Every one of these transitions requires its stated source status; a mismatched status fails with `ERR_REPORT_INVALID_TRANSITION`, and each advances the report's `version`.

Locking is the end of the road: a `SystemAdmin` moves an `APPROVED` report to the terminal `LOCKED`, advancing the `version`; locking does not freeze the `retention_release_date`, which keeps following the retention rule below.

Distribution is deliberately conservative. A `ProjectManager` adds recipients to a report that has reached `APPROVED` or `LOCKED` — any earlier state fails with `ERR_REPORT_NOT_APPROVED` — supplying `recipient_email`, which must be unique among the report's existing records (else `ERR_DUPLICATE_RECIPIENT`), and a `recipient_role` of `OWNER`, `ARCHITECT`, `INSPECTOR`, `SUBCONTRACTOR`, or `INTERNAL`. New records start `PENDING`. While the report's `distribution_hold` is true, creating a distribution record is refused with `ERR_DISTRIBUTION_HOLD`, and every `PENDING` record on the report stands flipped to `BLOCKED`; when the hold later clears, those `BLOCKED` records flip back to `PENDING` automatically. These automatic flips are ordinary record mutations, refreshing each flipped record's `updated_at` and `version`. Sending is a `SystemAdmin` act that moves `PENDING` to `SENT`. Following the validation order of §2.9, the record's own state precondition is evaluated before the distribution gates: a send against a record that is not `PENDING` — including one standing `BLOCKED` under a hold — fails with `ERR_DISTRIBUTION_INVALID_TRANSITION`, and only a `PENDING` send reaches the hold re-check, which refuses it with `ERR_DISTRIBUTION_HOLD` while the hold stands. Sending does not otherwise re-check the report's own status. A successful send stamps `sent_at` from the logical clock, recomputes the report's retention release, and advances the report's `version`. Acknowledgement by an `OwnerRep` moves `SENT` to the terminal `ACKNOWLEDGED` and stamps `acknowledged_at`; either action from the wrong status fails with `ERR_DISTRIBUTION_INVALID_TRANSITION`. Recipients may be removed only before dispatch: deleting a record is permitted from `PENDING` or `BLOCKED`, while a `SENT` or `ACKNOWLEDGED` record is retained for claims and its deletion fails with `ERR_DISTRIBUTION_ALREADY_SENT`. The register lists records filtered by `report_id` and `status`.

Retention ties the whole record together. A report's `retention_class` is `STANDARD` by default and flips to `CLAIMS_HOLD` the moment any linked incident is recordable; once set, the hold classification is sticky and survives the incident's closure. The `retention_release_date` is null while the class is `CLAIMS_HOLD`, and likewise null while no distribution record on the report has reached `SENT` or `ACKNOWLEDGED`; otherwise it is the latest `sent_at` among the report's sent or acknowledged records, plus the project's `retention_days`. The date recomputes on each distribution send and on incident-driven class changes, and it is not finalized at lock — a send against a record on a `LOCKED` report still advances the release date. A project, finally, can be closed only when every one of its reports has been locked — the gate of §3.1 that keeps the claims file complete.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and both guarded edits — return `200 OK`. The single deletion operation returns `204 No Content` with an empty data object. Readers reconstruct full request and response payloads from the narratives of §3; this table is deliberately minimal.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; recomputes incident lateness flags | SystemAdmin |
| POST | `/projects` | Create a project | SystemAdmin |
| GET | `/projects/{id}` | Get a project | All roles |
| GET | `/projects` | List projects | All roles |
| POST | `/projects/{id}/activate` | Activate a mobilizing project | SystemAdmin |
| POST | `/projects/{id}/suspend` | Suspend an active project | SystemAdmin |
| POST | `/projects/{id}/resume` | Resume a suspended project | SystemAdmin |
| POST | `/projects/{id}/close` | Close a project (all reports locked) | SystemAdmin |
| GET | `/projects/{id}/progress-summary` | Both progress variants side by side | All roles |
| POST | `/work-areas` | Create a work area | SystemAdmin |
| GET | `/work-areas/{id}` | Get a work area | All roles |
| GET | `/work-areas` | List work areas | All roles |
| POST | `/work-areas/{id}/close` | Close a work area | SystemAdmin |
| POST | `/work-areas/{id}/reopen` | Reopen a work area | SystemAdmin |
| POST | `/delivery-zones` | Create a delivery zone | SystemAdmin |
| GET | `/delivery-zones/{id}` | Get a delivery zone | All roles |
| GET | `/delivery-zones` | List delivery zones | All roles |
| POST | `/delivery-zones/{id}/close` | Close a delivery zone | SystemAdmin |
| POST | `/delivery-zones/{id}/reopen` | Reopen a delivery zone | SystemAdmin |
| POST | `/work-items` | Create a budgeted cost-code line | SystemAdmin |
| GET | `/work-items/{id}` | Get a work item | All roles |
| GET | `/work-items` | List work items | All roles |
| POST | `/daily-reports` | Create a daily report | Superintendent |
| GET | `/daily-reports/{id}` | Get a daily report with computed fields | All roles |
| GET | `/daily-reports` | List daily reports | All roles |
| PUT | `/daily-reports/{id}` | Edit report header (OCC-guarded, editable only) | Superintendent |
| POST | `/daily-reports/{id}/submit` | Submit with full precondition sweep | Superintendent |
| POST | `/daily-reports/{id}/start-review` | Begin project-manager review | ProjectManager |
| POST | `/daily-reports/{id}/approve` | Approve; cascades quantity rollup | ProjectManager |
| POST | `/daily-reports/{id}/request-revision` | Request revision on a report under review | ProjectManager |
| POST | `/daily-reports/{id}/return-to-draft` | Return a revision-requested report to draft | Superintendent |
| POST | `/daily-reports/{id}/recall` | Recall a submitted report (original submitter only) | Superintendent |
| POST | `/daily-reports/{id}/reopen` | Reopen an approved report; compensating rollup | ProjectManager |
| POST | `/daily-reports/{id}/lock` | Lock an approved report (terminal) | SystemAdmin |
| POST | `/crew-entries` | Add a manpower line to an editable report | Superintendent |
| GET | `/crew-entries/{id}` | Get a crew entry | All roles |
| GET | `/crew-entries` | List crew entries | All roles |
| POST | `/crew-entries/{id}/void` | Void a crew entry | Superintendent |
| POST | `/equipment-entries` | Add an equipment line with capacity check | Superintendent |
| GET | `/equipment-entries/{id}` | Get an equipment entry | All roles |
| GET | `/equipment-entries` | List equipment entries | All roles |
| POST | `/equipment-entries/{id}/void` | Void an equipment entry | Superintendent |
| POST | `/weather-observations` | Append a weather observation | Superintendent |
| GET | `/weather-observations/{id}` | Get a weather observation | All roles |
| GET | `/weather-observations` | List weather observations | All roles |
| POST | `/delay-events` | Record a delay window | Superintendent |
| GET | `/delay-events/{id}` | Get a delay event | All roles |
| GET | `/delay-events` | List delay events | All roles |
| POST | `/delay-events/{id}/classify` | Classify or re-classify a delay event | ProjectManager |
| POST | `/delay-events/{id}/dispute` | Dispute a classified delay event | OwnerRep |
| POST | `/delay-events/{id}/finalize` | Finalize a classified delay event | ProjectManager |
| POST | `/safety-observations` | Record a safety observation | SafetyOfficer |
| GET | `/safety-observations/{id}` | Get a safety observation | All roles |
| GET | `/safety-observations` | List safety observations | All roles |
| POST | `/safety-observations/{id}/mitigate` | Mark an observation mitigated | SafetyOfficer |
| POST | `/safety-observations/{id}/verify-close` | Verify-close a mitigated observation (different user) | SafetyOfficer |
| POST | `/safety-observations/{id}/reopen` | Reopen a mitigated observation | SafetyOfficer |
| POST | `/safety-observations/{id}/escalate` | Escalate an observation into an incident | SafetyOfficer |
| POST | `/incidents` | Capture an incident (any non-locked report) | SafetyOfficer |
| GET | `/incidents/{id}` | Get an incident | All roles |
| GET | `/incidents` | List incidents | All roles |
| POST | `/incidents/{id}/begin-investigation` | Begin incident investigation | SafetyOfficer |
| POST | `/incidents/{id}/notify-osha` | Record OSHA notification (recordable only) | SafetyOfficer |
| POST | `/incidents/{id}/close` | Close with a recordable or non-recordable outcome | SafetyOfficer |
| POST | `/media-attachments` | Attach photo or video tied to a work area | Superintendent, SafetyOfficer |
| GET | `/media-attachments/{id}` | Get a media attachment | All roles |
| GET | `/media-attachments` | List media attachments | All roles |
| POST | `/media-attachments/{id}/purge` | Purge media (forbidden when linked to an incident) | Superintendent, SafetyOfficer |
| POST | `/deliveries` | Log a material delivery with scheduled window | Superintendent |
| GET | `/deliveries/{id}` | Get a delivery | All roles |
| GET | `/deliveries` | List deliveries | All roles |
| POST | `/deliveries/{id}/inspect` | Record an inspection split | Superintendent |
| POST | `/deliveries/{id}/resolve-recount` | Resolve a pending recount to inspected | Superintendent |
| POST | `/quantity-entries` | Record installed quantity (OCC on report; supersedes) | Superintendent |
| GET | `/quantity-entries/{id}` | Get a quantity entry | All roles |
| GET | `/quantity-entries` | List quantity entries | All roles |
| POST | `/quantity-entries/{id}/void` | Void a quantity entry | Superintendent |
| POST | `/tm-tickets` | Create a T&M ticket with line arrays | Superintendent |
| GET | `/tm-tickets/{id}` | Get a T&M ticket | All roles |
| GET | `/tm-tickets` | List T&M tickets | All roles |
| PUT | `/tm-tickets/{id}` | Replace lines on a draft ticket (OCC on ticket) | Superintendent |
| POST | `/tm-tickets/{id}/submit-for-signature` | Submit a draft ticket for signatures | Superintendent |
| POST | `/tm-tickets/{id}/sign` | Sign as contractor then owner | ContractorRep, OwnerRep |
| POST | `/tm-tickets/{id}/approve` | Approve a fully signed ticket | ProjectManager |
| POST | `/tm-tickets/{id}/reject` | Reject a fully signed ticket | ProjectManager |
| POST | `/tm-tickets/{id}/revise` | Revise a rejected ticket back to draft | Superintendent |
| POST | `/tm-tickets/{id}/void` | Void a non-terminal ticket | Superintendent |
| POST | `/distribution-records` | Add a distribution recipient | ProjectManager |
| GET | `/distribution-records/{id}` | Get a distribution record | All roles |
| GET | `/distribution-records` | List distribution records | All roles |
| POST | `/distribution-records/{id}/send` | Send a pending record | SystemAdmin |
| POST | `/distribution-records/{id}/acknowledge` | Acknowledge a sent record | OwnerRep |
| DELETE | `/distribution-records/{id}` | Delete a pending or blocked record | ProjectManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_DELAY_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_OBSERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_MEDIA_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRIBUTION_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROJECT_INVALID_TRANSITION` | 409 Conflict |
| `ERR_WORK_AREA_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ZONE_INVALID_TRANSITION` | 409 Conflict |
| `ERR_REPORT_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ENTRY_INVALID_TRANSITION` | 409 Conflict |
| `ERR_DELAY_INVALID_TRANSITION` | 409 Conflict |
| `ERR_OBSERVATION_INVALID_TRANSITION` | 409 Conflict |
| `ERR_INCIDENT_INVALID_TRANSITION` | 409 Conflict |
| `ERR_DELIVERY_INVALID_TRANSITION` | 409 Conflict |
| `ERR_TICKET_INVALID_TRANSITION` | 409 Conflict |
| `ERR_MEDIA_INVALID_TRANSITION` | 409 Conflict |
| `ERR_DISTRIBUTION_INVALID_TRANSITION` | 409 Conflict |
| `ERR_REPORT_NOT_EDITABLE` | 409 Conflict |
| `ERR_INCIDENT_ON_LOCKED_REPORT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_HIGH_RISK_OBSERVATION_REQUIRES_MEDIA` | 422 Unprocessable Entity |
| `ERR_INCIDENT_NARRATIVE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INCIDENT_MEDIA_REQUIRED` | 409 Conflict |
| `ERR_OSHA_NOTIFICATION_REQUIRED` | 409 Conflict |
| `ERR_INCIDENT_RECORDABLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OSHA_NOT_APPLICABLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SIGNATURE_ORDER` | 409 Conflict |
| `ERR_DUPLICATE_CONTRACT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_WORK_AREA_CODE` | 409 Conflict |
| `ERR_DUPLICATE_ZONE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_COST_CODE` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_DATE` | 409 Conflict |
| `ERR_DUPLICATE_RECIPIENT` | 409 Conflict |
| `ERR_EQUIPMENT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MEDIA_LINK_CONSTRAINT` | 422 Unprocessable Entity |
| `ERR_GPS_INCOMPLETE_PAIR` | 422 Unprocessable Entity |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_TICKET_EMPTY` | 422 Unprocessable Entity |
| `ERR_INSPECTION_QTY_OVERFLOW` | 422 Unprocessable Entity |
| `ERR_MEDIA_LINKED_TO_INCIDENT` | 409 Conflict |
| `ERR_REPORT_DATE_FUTURE` | 422 Unprocessable Entity |
| `ERR_WEATHER_OUTSIDE_REPORT_DATE` | 422 Unprocessable Entity |
| `ERR_MEDIA_CAPTURED_OUTSIDE_REPORT_DATE` | 422 Unprocessable Entity |
| `ERR_INCIDENT_OCCURRED_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_DELAY_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_DELAY_OVERLAP_COMPENSABLE` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WORK_AREA_CLOSED` | 409 Conflict |
| `ERR_DELIVERY_ZONE_CLOSED` | 409 Conflict |
| `ERR_MEDIA_REPORT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WEATHER_MISSING` | 409 Conflict |
| `ERR_NO_WORK_RECORDED` | 409 Conflict |
| `ERR_WORK_ENTRIES_CONFLICT` | 409 Conflict |
| `ERR_DELIVERY_NOT_INSPECTED` | 409 Conflict |
| `ERR_DELAY_EVENT_UNCLASSIFIED` | 409 Conflict |
| `ERR_REPORT_NOT_APPROVED` | 409 Conflict |
| `ERR_DISTRIBUTION_HOLD` | 409 Conflict |
| `ERR_DISTRIBUTION_ALREADY_SENT` | 409 Conflict |
| `ERR_DELAY_FINALIZE_REQUIRES_SUBMITTED_REPORT` | 409 Conflict |
| `ERR_DELAY_LOCKED_REPORT` | 409 Conflict |
| `ERR_PROJECT_HAS_OPEN_REPORTS` | 409 Conflict |
| `ERR_PROJECT_NOT_ACTIVE` | 409 Conflict |
| `ERR_TICKET_REPORT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_TM_CEILING_EXCEEDED` | 422 Unprocessable Entity |
